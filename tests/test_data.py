"""Tests for the stage-as-data C prototype (spec:
2026-10-05-stage-as-data-c-prototype.md): the prim-level numeric projection,
the `where:<metric><op><n>` predicate, and the Table outputs.

Parse tests are pure (no pxr -> run in the bare CI); projection and seed
resolution are pxr-gated.
"""
import json

import pytest

from weft import ask
from weft import data


# -- pure: the metric registry + predicate parsing (bare CI) ----------------

def test_registry_tiers_disjoint_and_selectable_is_cheap():
    assert set(data.CHEAP_METRICS).isdisjoint(data.EXPENSIVE_METRICS)
    # only numeric cheap metrics are selectable in the grammar
    assert data.SELECTABLE_METRICS <= set(data.CHEAP_METRICS)
    assert "point_count" not in data.SELECTABLE_METRICS
    assert "bbox_volume" in data.SELECTABLE_METRICS


def test_parse_metric_predicate():
    s = ask.parse_seed("where:bbox_volume>100")
    assert s.plane == "metric" and s.key == "bbox_volume" and s.value == ">100"
    s = ask.parse_seed("where:centroid_y>=0")
    assert s.plane == "metric" and s.key == "centroid_y" and s.value == ">=0"


def test_parse_facet_still_works():
    s = ask.parse_seed("where:finish=translucent")
    assert s.plane == "attr" and s.key == "finish" and s.value == "translucent"


def test_parse_metric_rejections():
    with pytest.raises(ValueError):
        ask.parse_seed("where:bbox_volume~5")          # reserved combinator
    with pytest.raises(ValueError):
        ask.parse_seed("where:nope>5")                 # not a metric
    with pytest.raises(ValueError):
        ask.parse_seed("where:point_count>5")          # expensive: not selectable
    with pytest.raises(ValueError):
        ask.parse_seed("where:bbox_volume>abc")        # not a number


def test_compare():
    assert data.compare(10.0, ">", 5)
    assert not data.compare(3.0, ">", 5)
    assert data.compare(5.0, ">=", 5)
    assert data.compare(5.0, "==", 5)
    assert data.compare(4.0, "!=", 5)


# -- pxr-gated: projection + resolution + outputs ---------------------------

GEO = """#usda 1.0
( defaultPrim = "geo" )
def Xform "geo"
{
    def Mesh "shape"
    {
        point3f[] points = [(-1,-1,0),(1,-1,0),(1,1,0),(-1,1,0)]
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0,1,2,3]
    }
}
"""

MAIN = """#usda 1.0
( defaultPrim = "root" )
def Xform "root"
{
    def Xform "big"
    {
        float3[] extentsHint = [(-5, -5, -5), (5, 5, 5)]
        double3 xformOp:translate = (0, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Xform "small"
    {
        float3[] extentsHint = [(-1, -1, -1), (1, 1, 1)]
        double3 xformOp:translate = (20, 0, 0)
        uniform token[] xformOpOrder = ["xformOp:translate"]
    }
    def Mesh "inline_mesh"
    {
        float3[] extentsHint = [(-1, -1, -1), (1, 1, 1)]
        point3f[] points = [(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)]
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
    }
    def Xform "payloaded" (
        prepend payload = @./geo.usda@
    )
    {
        float3[] extentsHint = [(-1, -1, -1), (1, 1, 1)]
    }
}
"""


@pytest.fixture
def stage(tmp_path):
    Usd = pytest.importorskip("pxr.Usd")
    (tmp_path / "geo.usda").write_text(GEO)
    (tmp_path / "main.usda").write_text(MAIN)
    return Usd.Stage.Open(str(tmp_path / "main.usda"), Usd.Stage.LoadNone)


def _row(tbl, path):
    return next(r for r in tbl.rows() if r["path"] == path)


def test_cheap_metrics_no_load(stage):
    tbl = data.project(stage, columns=["bbox_volume", "centroid_x", "type"])
    big, small = _row(tbl, "/root/big"), _row(tbl, "/root/small")
    assert big["bbox_volume"] == pytest.approx(1000.0)   # 10*10*10
    assert small["bbox_volume"] == pytest.approx(8.0)     # 2*2*2
    assert big["centroid_x"] == pytest.approx(0.0)
    assert small["centroid_x"] == pytest.approx(20.0)     # world translate
    assert big["type"] == "Xform"


def test_expensive_none_until_loaded(stage):
    tbl = data.project(stage, columns=["point_count", "poly_count"])
    # inline mesh: geometry present without any payload -> computable
    assert _row(tbl, "/root/inline_mesh")["point_count"] == 4
    assert _row(tbl, "/root/inline_mesh")["poly_count"] == 1
    # payloaded: unloaded -> honest None, never a fabricated 0
    assert _row(tbl, "/root/payloaded")["point_count"] is None

    stage.Load("/root/payloaded")
    tbl2 = data.project(stage, columns=["point_count", "poly_count"])
    assert _row(tbl2, "/root/payloaded")["point_count"] == 4
    assert _row(tbl2, "/root/payloaded")["poly_count"] == 1


def test_bbox_volume_none_without_hint(tmp_path):
    Usd = pytest.importorskip("pxr.Usd")
    (tmp_path / "s.usda").write_text(
        '#usda 1.0\n(defaultPrim="root")\ndef Xform "root"\n'
        '{\n    def Xform "nohint" {}\n}\n')
    st = Usd.Stage.Open(str(tmp_path / "s.usda"), Usd.Stage.LoadNone)
    tbl = data.project(st, columns=["bbox_volume"])
    assert _row(tbl, "/root/nohint")["bbox_volume"] is None


def test_metric_seed_selects_without_load(stage):
    res = ask.resolve_seeds(stage, ["where:bbox_volume>100"])
    assert res[0].paths == ["/root/big"]          # only the 1000-volume prim
    # the payloaded prim was NOT loaded to decide this (cheap selection is
    # surgical). Payload-less prims report IsLoaded()==True -- nothing to load.
    assert not stage.GetPrimAtPath("/root/payloaded").IsLoaded()


def test_table_outputs(stage, tmp_path):
    tbl = data.project(stage, columns=["bbox_volume", "type"])
    assert "path" in tbl.names and "bbox_volume" in tbl.names
    rows = tbl.rows()
    assert len(rows) == 5          # /root + its 4 children

    tbl.to_json(str(tmp_path / "t.json"))
    loaded = json.loads((tmp_path / "t.json").read_text())
    assert any(r["path"] == "/root/big" for r in loaded)

    tbl.to_csv(str(tmp_path / "t.csv"))
    assert (tmp_path / "t.csv").read_text().startswith("path,")


def test_to_numpy_optional(stage):
    pytest.importorskip("numpy")
    cols = data.project(stage, columns=["bbox_volume"]).to_numpy()
    assert "bbox_volume" in cols and len(cols["path"]) == 5   # /root + 4 children
