"""Tests for weft/threadgraph.py -- the pure, Qt-free graph builder behind
the "Weft Threads" usdview panel (extras/usdview/weftViewer/threadpanel.py).

Mirrors the pxr-gated style of tests/test_usdview_core.py and
tests/test_alab_pull.py: a synthetic-stage suite that needs only `pxr`, plus
an acceptance suite gated on WEFT_ALAB/JITSD_ALAB that pins the exact
node/edge counts the scratchpad spike (threadgraph4.py) measured against the
real ALab workbench, so this reimplementation is checked against the proven
one, not just against itself."""

from __future__ import annotations

import os

import pytest

pxr = pytest.importorskip("pxr")

from weft.threadgraph import build_graph  # noqa: E402

# -- synthetic-stage suite ---------------------------------------------------
#
# Mimics ALab's own root -> group -> placement convention just closely
# enough to exercise every source build_graph reads: hierarchy, a Mount
# contract with a carrier, and (via alab_root) finish/shading facets from an
# interface file on disk.

SCENE = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "shelf01"
    {
        def Xform "chemistry_bottle01_0001"
        {
            uniform token weft:offer:contract = "Mount@1"
            rel weft:offer:carrier = </root/shelf01/furniture_shelf01_0001>
        }
        def Xform "furniture_shelf01_0001"
        {
        }
        def Xform "not_a_placement"
        {
        }
    }
}
"""


@pytest.fixture
def scene_stage(tmp_path):
    from pxr import Usd
    p = tmp_path / "scene.usda"
    p.write_text(SCENE)
    return Usd.Stage.Open(str(p))


def test_hierarchy_edges_present(scene_stage):
    g = build_graph(scene_stage)
    hier = [e for e in g["edges"] if e["kind"] == "usd:arc"]
    assert {"source": "/root/shelf01",
             "target": "/root/shelf01/chemistry_bottle01_0001",
             "kind": "usd:arc"} in hier
    assert {"source": "/root/shelf01",
             "target": "/root/shelf01/furniture_shelf01_0001",
             "kind": "usd:arc"} in hier


def test_non_placement_children_are_skipped(scene_stage):
    g = build_graph(scene_stage)
    ids = {n["id"] for n in g["nodes"]}
    assert "/root/shelf01/not_a_placement" not in ids


def test_group_and_placement_node_shape(scene_stage):
    g = build_graph(scene_stage)
    by_id = {n["id"]: n for n in g["nodes"]}
    grp = by_id["/root/shelf01"]
    assert grp["type"] == "group" and grp["label"] == "shelf01"

    prop = by_id["/root/shelf01/chemistry_bottle01_0001"]
    assert prop["type"] == "prop"
    assert prop["asset"] == "chemistry_bottle01"
    assert prop["group"] == "shelf01"

    furniture = by_id["/root/shelf01/furniture_shelf01_0001"]
    assert furniture["type"] == "furniture"


def test_contract_kind_derived_from_offer_value(scene_stage):
    g = build_graph(scene_stage)
    mount_edges = [e for e in g["edges"] if e["kind"] == "Mount"]
    assert mount_edges == [{
        "source": "/root/shelf01/chemistry_bottle01_0001",
        "target": "/root/shelf01/furniture_shelf01_0001",
        "kind": "Mount",
    }]


def test_kinds_lists_every_present_kind_once(scene_stage):
    g = build_graph(scene_stage)
    assert g["kinds"] == ["usd:arc", "Mount"]


def test_degree_counts_incoming_and_outgoing(scene_stage):
    g = build_graph(scene_stage)
    by_id = {n["id"]: n for n in g["nodes"]}
    # chemistry_bottle01_0001: one incoming (usd:arc from the group), one
    # outgoing (Mount to the carrier) -> degree 2.
    assert by_id["/root/shelf01/chemistry_bottle01_0001"]["deg"] == 2
    # the group: one outgoing edge per placement -> degree 2.
    assert by_id["/root/shelf01"]["deg"] == 2


def test_facets_read_from_interface_file_when_alab_root_given(scene_stage, tmp_path):
    iface_dir = tmp_path / "entity" / "chemistry_bottle01" / "interface"
    iface_dir.mkdir(parents=True)
    (iface_dir / "chemistry_bottle01_interface.usda").write_text(
        'uniform token weft:bind:finish = "translucent"\n'
        'uniform token[] weft:bind:shading = ["usd_full", "usd_preview"]\n'
    )
    g = build_graph(scene_stage, alab_root=str(tmp_path))
    by_id = {n["id"]: n for n in g["nodes"]}
    assert by_id["finish:translucent"]["type"] == "finish"
    assert by_id["shading:usd_full"]["type"] == "shading"
    assert by_id["shading:usd_preview"]["type"] == "shading"
    finish_edges = [e for e in g["edges"] if e["kind"] == "weft:bind:finish"]
    assert finish_edges == [{
        "source": "/root/shelf01/chemistry_bottle01_0001",
        "target": "finish:translucent",
        "kind": "weft:bind:finish",
    }]
    assert "weft:bind:finish" in g["kinds"]
    assert "weft:bind:shading" in g["kinds"]


def test_no_facets_when_alab_root_not_given_or_not_found(scene_stage):
    g = build_graph(scene_stage)  # alab_root=None, not derivable from a tmp_path stage
    assert not any(n["type"] in ("finish", "shading") for n in g["nodes"])
    g2 = build_graph(scene_stage, alab_root="/no/such/directory")
    assert not any(n["type"] in ("finish", "shading") for n in g2["nodes"])


def test_degrades_gracefully_without_a_root_prim(tmp_path):
    """No /root at all -- a totally different stage shape. Never raises: it
    falls back to the pseudo-root's own children as "groups" (here just
    "World"), and since none of ITS children match the <asset>_<NNNN>
    placement-naming convention, that's as far as it gets -- a harmless
    single disconnected group node, not a crash and not a fabricated
    hierarchy."""
    from pxr import Usd
    p = tmp_path / "other.usda"
    p.write_text("""#usda 1.0
(
    defaultPrim = "World"
)

def Xform "World"
{
    def Xform "Child"
    {
    }
}
""")
    stage = Usd.Stage.Open(str(p))
    g = build_graph(stage)
    assert g["nodes"] == [{"id": "/World", "label": "World", "type": "group", "deg": 0}]
    assert g["edges"] == []
    assert g["kinds"] == []


# -- acceptance: the real ALab workbench, pinned to the proven spike's own
#    measured output (scratchpad's threadgraph4.py) -----------------------

ALAB = os.environ.get("WEFT_ALAB") or os.environ.get("JITSD_ALAB")
WORKBENCH = "entity/lab_workbench01/lab_workbench01.usda"


@pytest.mark.skipif(not ALAB, reason="set WEFT_ALAB to the ALab directory to run acceptance")
def test_build_graph_against_real_alab_workbench():
    from pxr import Usd
    stage = Usd.Stage.Open(os.path.join(ALAB, WORKBENCH))
    g = build_graph(stage)

    assert len(g["nodes"]) == 152
    assert len(g["edges"]) == 1018
    assert g["kinds"] == ["usd:arc", "Mount", "weft:bind:shading", "weft:bind:finish"]

    kinds_present = {e["kind"] for e in g["edges"]}
    assert kinds_present == {"usd:arc", "Mount", "weft:bind:shading", "weft:bind:finish"}

    # hierarchy present
    assert any(e["kind"] == "usd:arc" for e in g["edges"])
    # Mount present, with a real carrier target
    mount = [e for e in g["edges"] if e["kind"] == "Mount"]
    assert mount
    by_id = {n["id"]: n for n in g["nodes"]}
    assert any(by_id[e["target"]]["type"] == "furniture" for e in mount)


@pytest.mark.skipif(not ALAB, reason="set WEFT_ALAB to the ALab directory to run acceptance")
def test_build_graph_identical_on_an_unloaded_stage():
    """The Weft Threads usdview panel is built to run against a stage
    opened with `--unloaded` (see extras/usdview/README.md's "bounding
    boxes that condense into geometry" invocation) -- build_graph must see
    the exact same hierarchy either way, not just when everything happens
    to already be loaded. Pins the regression this caught: GetChildren()'s
    own default predicate silently drops any prim whose payload isn't
    loaded yet, which on an --unloaded ALab stage is nearly the whole
    tree (152 real nodes -> 9 before the fix); the fix must not
    OVER-correct either -- Usd.PrimAllPrimsPredicate is too permissive and
    pulled in abstract/inactive placeholder prims, nearly tripling the
    count (152 -> 447) in earlier testing -- so this also guards against
    regressing back to that."""
    from pxr import Usd
    loaded_stage = Usd.Stage.Open(os.path.join(ALAB, WORKBENCH))
    unloaded_stage = Usd.Stage.Open(os.path.join(ALAB, WORKBENCH), load=Usd.Stage.LoadNone)

    g_loaded = build_graph(loaded_stage)
    g_unloaded = build_graph(unloaded_stage)

    assert len(g_unloaded["nodes"]) == len(g_loaded["nodes"]) == 152
    assert len(g_unloaded["edges"]) == len(g_loaded["edges"]) == 1018
    assert {n["id"] for n in g_unloaded["nodes"]} == {n["id"] for n in g_loaded["nodes"]}
