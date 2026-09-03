"""Pure logic for the weft usdview plugin: no Qt imports, only pxr and weft.

The Qt shell (`__init__.py`) calls into this module and renders whatever
comes back; everything here is unit-testable without a running usdview
(see tests/test_usdview_core.py)."""

from __future__ import annotations

from typing import List, Sequence, Tuple

from weft.ask import resolve_seeds
from weft.pull import edge_kind_of, who as _who

# The customData key authored on every prim Solo threads deactivates (spec:
# "set customData key 'weft:solo' = true on the overs we author so restore
# is robust across invocations"). NOTE: Usd namespaces customData keys on
# the ":" the same way it namespaces attributes, so this key is NOT stored
# as a flat {"weft:solo": True} entry -- it composes to
# {"weft": {"solo": True}}. Always read/write it through the *composed*
# Usd.Prim API (GetCustomDataByKey/SetCustomDataByKey/ClearCustomDataByKey),
# which resolves that nesting correctly; parsing raw Sdf.PrimSpec.customData
# by hand will silently miss it.
MARKER_KEY = "weft:solo"


def deactivation_set(stage, member_paths: Sequence[str]) -> List[str]:
    """The minimal "view solo" frontier.

    For each level along the members' ancestor spines, the sibling prims
    that are neither members nor themselves on any member's spine.

    - Never a member (it stays active -- that's the point of solo-ing it).
    - Never a descendant of a member: recursion stops the moment a child IS
      a member: its own children are never visited, so nothing under it is
      ever added to the frontier.
    - Never an ancestor of a member: a spine prim is recursed INTO (its
      siblings-of-the-next-level get judged), never added to the frontier
      itself -- deactivating an ancestor would hide the member along with
      everything else under that ancestor.

    Caller's responsibility, not this function's: `stage` must be fully
    active (no leftover `weft:solo` deactivations) before calling this.
    `GetChildren()` uses the default (active-only) predicate, so it cannot
    see -- and therefore cannot correctly route a spine through -- a prim a
    PREVIOUS call already deactivated. A second Solo threads run without an
    intervening restore would silently compute the wrong frontier (or drop
    the new member's own subtree entirely, if the member sits below an
    already-deactivated ancestor). Call `restore_set` + reactivate first.
    """
    from pxr import Sdf

    members = set(member_paths)
    spine = set()
    for m in members:
        anc = Sdf.Path(m).GetParentPath()
        while not anc.isEmpty and anc != Sdf.Path.absoluteRootPath:
            spine.add(anc.pathString)
            anc = anc.GetParentPath()

    frontier: List[str] = []

    def visit(prim) -> None:
        for child in prim.GetChildren():
            cp = child.GetPath().pathString
            if cp in members:
                continue
            if cp in spine:
                visit(child)
            else:
                frontier.append(cp)

    visit(stage.GetPseudoRoot())
    return sorted(frontier)


def restore_set(stage) -> List[str]:
    """Every prim path currently carrying the `weft:solo` deactivation
    marker -- what "Restore world" reactivates, and what a fresh Solo
    threads run must reactivate FIRST (see `deactivation_set`'s docstring)
    before computing a new frontier on a clean stage.

    `Usd.PrimAllPrimsPredicate` is required, not the stage's default
    traversal predicate: a marked prim is, by definition, inactive, and the
    default predicate excludes inactive prims entirely -- Traverse()ing with
    it would never find anything to restore."""
    from pxr import Usd

    return sorted(
        prim.GetPath().pathString
        for prim in stage.Traverse(Usd.PrimAllPrimsPredicate)
        if prim.GetCustomDataByKey(MARKER_KEY)
    )


def edge_kinds(stage, paths: Sequence[str]) -> List[str]:
    """Kinds named by the selection's own outgoing (authored) relationships
    -- the checklist source for the Solo threads follow-picker. Reuses
    `weft.pull.edge_kind_of`; does not reimplement `weft.pull`'s full edge
    extraction (contract carriers, extractors), which needs a `Pull` in
    progress to make sense of."""
    kinds = set()
    for path in paths:
        prim = stage.GetPrimAtPath(path)
        if not prim:
            continue
        for rel in prim.GetAuthoredRelationships():
            kinds.add(edge_kind_of(rel.GetName()))
    return sorted(kinds)


def ask_rows(stage, text: str) -> Tuple[List[str], str]:
    """One `Ask...` query resolved against the LIVE stage: the matched
    paths, and the resolution declaration line (mode, matched, complement,
    note) -- the same line shape `weft pull` prints per seed."""
    r = resolve_seeds(stage, [text])[0]
    line = "seed %s -> %d (%s" % (r.seed.raw, r.matched, r.mode)
    if r.complement:
        line += ", %d do not author the key" % r.complement
    line += ")"
    if r.note:
        line += "  %s" % r.note
    return list(r.paths), line


def who_rows(context_file: str, paths: Sequence[str], depth: int = 1
             ) -> List[Tuple[str, str, str]]:
    """Incoming edges onto `paths`: (source, kind, member) rows, straight
    from `weft.pull.who` -- reused, not reshaped."""
    seeds = ["path:%s" % p for p in paths]
    return _who(context_file, seeds, depth=depth)


def receipt_text(p) -> str:
    """The last pull's receipt, in the same shape `weft pull` prints to the
    terminal: resolutions, members, boundary by kind with omission class,
    declarations, fitness."""
    lines: List[str] = []
    for r in p.resolutions:
        line = "seed %s -> %d (%s" % (r.seed.raw, r.matched, r.mode)
        if r.complement:
            line += ", %d do not author the key" % r.complement
        line += ")"
        if r.note:
            line += "  %s" % r.note
        lines.append(line)
    lines.append("members (%d):" % len(p.members))
    for m in p.members:
        via = "seed" if m.via_kind == "seed" else "%s <- %s" % (m.via_kind, m.from_member)
        lines.append("  %-44s %s" % (m.path, via))
    if p.boundary:
        lines.append("boundary (%d):" % len(p.boundary))
        for b in p.boundary:
            lines.append("  %-44s %-24s %s [%s]" % (b.target, b.kind, b.reason, b.omission))
    for d in p.declarations:
        lines.append("  ~ %s" % d)
    lines.append("fitness: %s" % p.fitness.get("statement", ""))
    return "\n".join(lines)
