"""Pure-logic tests for the weft usdview plugin's core.py -- no Qt, no
usdview. Mirrors the pxr-gated style of tests/test_pull.py and
tests/test_manifest.py."""

import sys
from pathlib import Path

import pytest

pxr = pytest.importorskip("pxr")

# extras/usdview isn't an installed package (see pyproject.toml's
# [tool.setuptools] packages list -- deliberately just weft/deps/absent), so
# make it importable the same way the repo root already is for `weft`/`deps`
# in an editable/dev install: put the repo root on sys.path.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from extras.usdview.weftViewer.core import (  # noqa: E402
    MARKER_KEY, ask_rows, deactivation_set, edge_kinds, receipt_text,
    restore_set, who_rows,
)
from weft.pull import pull  # noqa: E402


# -- deactivation_set -------------------------------------------------------

HIER = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "A"
    {
        def Xform "Member1"
        {
            def Xform "Child1"
            {
            }
        }
        def Xform "Sibling1"
        {
        }
    }
    def Xform "B"
    {
        def Xform "Member2"
        {
        }
        def Xform "Sibling2"
        {
        }
    }
    def Xform "C"
    {
        def Xform "Deep"
        {
        }
    }
}
"""


@pytest.fixture
def hier_stage(tmp_path):
    from pxr import Usd
    p = tmp_path / "hier.usda"
    p.write_text(HIER)
    return Usd.Stage.Open(str(p))


def test_deactivation_set_two_members_different_branches(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1", "/World/B/Member2"])
    assert got == ["/World/A/Sibling1", "/World/B/Sibling2", "/World/C"]


def test_deactivation_set_never_touches_members(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1", "/World/B/Member2"])
    assert "/World/A/Member1" not in got
    assert "/World/B/Member2" not in got


def test_deactivation_set_never_touches_member_descendants(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1", "/World/B/Member2"])
    assert "/World/A/Member1/Child1" not in got


def test_deactivation_set_never_touches_spine_ancestors(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1", "/World/B/Member2"])
    assert "/World" not in got
    assert "/World/A" not in got
    assert "/World/B" not in got


def test_deactivation_set_unrelated_branch_deactivated_as_one_unit(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1", "/World/B/Member2"])
    # /World/C is untouched by any member's spine, so the whole subtree is
    # covered by deactivating C itself -- its descendant is never separately
    # listed.
    assert "/World/C" in got
    assert "/World/C/Deep" not in got


def test_deactivation_set_single_member(hier_stage):
    got = deactivation_set(hier_stage, ["/World/A/Member1"])
    assert got == ["/World/A/Sibling1", "/World/B", "/World/C"]


# -- restore-before-solo (review Finding 1) ----------------------------------
#
# deactivation_set's GetChildren() walk uses the default (active-only)
# predicate, so a prim a PREVIOUS Solo threads call deactivated is invisible
# to a second call -- it can't be recognised as spine, so the walk cannot
# route through it, and any member living beneath it silently vanishes from
# the composed stage instead of raising. The fix is that a Solo threads run
# ALWAYS restores first (the exact code path Restore world uses) before
# computing a fresh deactivation_set. This section pins that invariant at
# the pure-logic level: the same sequence of authoring calls _runSolo and
# _runRestore make, without any Qt involved.

CROSS = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "X"
    {
        def Xform "A"
        {
        }
        def Xform "Sibling1"
        {
        }
    }
    def Xform "Y"
    {
        def Xform "B"
        {
        }
        def Xform "Sibling2"
        {
        }
    }
}
"""


@pytest.fixture
def cross_stage(tmp_path):
    from pxr import Usd
    p = tmp_path / "cross.usda"
    p.write_text(CROSS)
    return Usd.Stage.Open(str(p))


def _author_solo(stage, member_paths):
    """The same authoring `_runSolo` does: compute the frontier, deactivate
    it, mark it."""
    from pxr import Usd
    session = stage.GetSessionLayer()
    frontier = deactivation_set(stage, member_paths)
    with Usd.EditContext(stage, session):
        for path in frontier:
            prim = stage.GetPrimAtPath(path)
            if prim and prim.IsActive():
                prim.SetActive(False)
                prim.SetCustomDataByKey(MARKER_KEY, True)
    return frontier


def _author_restore(stage):
    """The same authoring `_runRestore` does: reactivate everything
    `restore_set` currently reports."""
    from pxr import Usd
    session = stage.GetSessionLayer()
    marked = restore_set(stage)
    with Usd.EditContext(stage, session):
        for path in marked:
            prim = stage.GetPrimAtPath(path)
            if prim:
                prim.ClearActive()
                prim.ClearCustomDataByKey(MARKER_KEY)
    return marked


def test_second_solo_without_restore_first_loses_the_new_member(cross_stage):
    """Demonstrates the bug the fix closes: skip the restore, and B --
    living under /World/Y, which the FIRST solo deactivated as an unrelated
    branch -- never even composes for the second solo to find."""
    stage = cross_stage
    _author_solo(stage, ["/World/X/A"])
    # /World/Y (and therefore B beneath it) is gone from the composed stage.
    assert not stage.GetPrimAtPath("/World/Y/B").IsValid()

    # A second solo for B, WITHOUT restoring first: deactivation_set can't
    # even see the inactive /World/Y branch, let alone route a spine
    # through it to protect B.
    frontier = deactivation_set(stage, ["/World/Y/B"])
    assert "/World/Y" not in frontier  # never visited -- invisible, not "kept"
    assert stage.GetPrimAtPath("/World/Y/B").IsValid() is False  # still broken


def test_second_solo_restores_first_and_computes_correctly(cross_stage):
    stage = cross_stage

    # First solo: member A, under /World/X.
    first = _author_solo(stage, ["/World/X/A"])
    assert first == ["/World/X/Sibling1", "/World/Y"]
    assert not stage.GetPrimAtPath("/World/Y/B").IsValid()

    # _runSolo's restore-before-solo step: a full restore, same code path
    # Restore world uses, before computing anything new.
    restored = _author_restore(stage)
    assert set(restored) == {"/World/X/Sibling1", "/World/Y"}
    assert restore_set(stage) == []  # A's markers are gone

    # B composes again now that Y is reactivated, and a fresh solo for B
    # computes the correct frontier.
    b = stage.GetPrimAtPath("/World/Y/B")
    assert b.IsValid() and b.IsActive()
    second = _author_solo(stage, ["/World/Y/B"])
    assert second == ["/World/X", "/World/Y/Sibling2"]

    b = stage.GetPrimAtPath("/World/Y/B")
    assert b.IsValid() and b.IsActive()
    x = stage.GetPrimAtPath("/World/X")
    assert x.IsValid() and not x.IsActive()
    # No leftover marker from the first solo -- restore_set only reports
    # what's CURRENTLY marked.
    assert set(restore_set(stage)) == {"/World/X", "/World/Y/Sibling2"}


# -- instance-proxy widening (review included Minor) -------------------------
#
# Pins the emergent invariant the review identified: pull()'s `_admit`
# widens any instance-proxy path up to its instance root (USD instances
# populate prototypes whole-or-not-at-all), and deactivation_set's
# GetChildren() walk -- default predicate -- never descends INTO an
# instance's own prototype, so it can never emit an instance-proxy path
# either. The two invariants have to agree, or a member path from pull()
# could name a prim deactivation_set would never treat as a member.

INSTANCED = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    class Xform "_class_Widget"
    {
        def Xform "Inner"
        {
        }
    }

    def Xform "Instance" (
        instanceable = true
        inherits = </World/_class_Widget>
    )
    {
    }

    def Xform "Sibling"
    {
    }
}
"""


@pytest.fixture
def instanced_ctx(tmp_path):
    p = tmp_path / "instanced.usda"
    p.write_text(INSTANCED)
    return str(p)


def test_ask_and_pull_widen_instance_proxy_to_instance_root(instanced_ctx):
    from pxr import Usd

    stage = Usd.Stage.Open(instanced_ctx)
    inner = stage.GetPrimAtPath("/World/Instance/Inner")
    assert inner.IsValid() and inner.IsInstanceProxy()

    # An ask seeding the instance-proxy path directly (as "Who depends on
    # this?"/Solo threads would build from a live selection under the
    # instance).
    rows, _declaration = ask_rows(stage, "path:/World/Instance/Inner")
    assert rows == ["/World/Instance/Inner"]

    # Fed through pull() as a path: seed, the member that actually lands is
    # the widened instance ROOT, not the proxy path.
    p = pull(instanced_ctx, ["path:/World/Instance/Inner"], follow=[])
    member_paths = [m.path for m in p.members]
    assert member_paths == ["/World/Instance"]
    assert "/World/Instance/Inner" not in member_paths

    # deactivation_set over that (correct) member set never emits an
    # instance-proxy path -- there is nothing under an instance's own
    # prototype for its default-predicate GetChildren() walk to reach.
    frontier = deactivation_set(stage, member_paths)
    assert frontier == ["/World/Sibling"]
    assert not any(stage.GetPrimAtPath(p).IsInstanceProxy() for p in frontier)


# -- ask_rows / who_rows / receipt_text -------------------------------------

CTX = """#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
    }
    def Xform "widget_0001"
    {
        rel material:binding = </World/Looks/glass>
        rel physics:carries = </World/widget_0002>
    }
    def Xform "widget_0002"
    {
    }
    def Xform "gadget_0001"
    {
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


@pytest.fixture
def ctx_stage(ctx):
    from pxr import Usd
    return Usd.Stage.Open(ctx)


def test_ask_rows_matches_and_declares(ctx_stage):
    rows, declaration = ask_rows(ctx_stage, "widget_*")
    assert rows == ["/World/widget_0001", "/World/widget_0002"]
    assert "seed widget_* -> 2" in declaration
    assert "lexical" in declaration


def test_ask_rows_single_match(ctx_stage):
    rows, declaration = ask_rows(ctx_stage, "widget_0001")
    assert rows == ["/World/widget_0001"]
    assert "-> 1" in declaration


def test_ask_rows_no_match_notes_it(ctx_stage):
    rows, declaration = ask_rows(ctx_stage, "nope_*")
    assert rows == []
    assert "matched nothing" in declaration


def test_ask_rows_reserved_operator_raises(ctx_stage):
    with pytest.raises(ValueError):
        ask_rows(ctx_stage, "where:foo~bar")


def test_edge_kinds_reports_authored_relationship_kinds(ctx_stage):
    kinds = edge_kinds(ctx_stage, ["/World/widget_0001"])
    assert kinds == ["material:binding", "physics:carries"]


def test_edge_kinds_empty_for_leaf_with_no_relationships(ctx_stage):
    assert edge_kinds(ctx_stage, ["/World/widget_0002"]) == []


def test_edge_kinds_missing_path_ignored(ctx_stage):
    assert edge_kinds(ctx_stage, ["/World/does_not_exist"]) == []


def test_who_rows_reports_incoming_edges(ctx):
    rows = who_rows(ctx, ["/World/widget_0002"], depth=1)
    assert rows == [("/World/widget_0001", "physics:carries", "/World/widget_0002")]


def test_who_rows_none_for_prim_with_no_incoming_edges(ctx):
    assert who_rows(ctx, ["/World/gadget_0001"], depth=1) == []


def test_receipt_text_contains_boundary_kinds_and_omission_classes(ctx):
    p = pull(ctx, ["widget_0001"], follow=[])
    text = receipt_text(p)
    assert "members (1):" in text
    assert "/World/widget_0001" in text
    assert "boundary (2):" in text
    # material:binding is not in the physics:/skel: prefix list -> inert.
    assert "material:binding" in text
    assert "[inert]" in text
    # physics:carries IS the meaning-changing prefix.
    assert "physics:carries" in text
    assert "[meaning-changing]" in text
    assert "fitness:" in text


def test_receipt_text_resolution_line_matches_ask_rows_shape(ctx):
    p = pull(ctx, ["widget_0001"], follow=[])
    text = receipt_text(p)
    _rows, declaration = ask_rows(
        __import__("pxr").Usd.Stage.Open(ctx), "widget_0001")
    assert declaration in text
