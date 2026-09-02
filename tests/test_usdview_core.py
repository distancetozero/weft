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
    ask_rows, deactivation_set, edge_kinds, receipt_text, who_rows,
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
