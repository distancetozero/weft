"""derive-real (spec 2026-10-06): native material-binding kind (auto), the
opacity-finish rule deriver (declared), and named-attribute data columns.
pxr-gated; USD authoring, so needs usd-core."""
import pytest

SCENE = """#usda 1.0
( defaultPrim = "root" )
def Xform "root"
{
    def Scope "mtl"
    {
        def Material "glass"
        {
            token outputs:surface.connect = </root/mtl/glass/pbr.outputs:surface>
            def Shader "pbr"
            {
                uniform token info:id = "UsdPreviewSurface"
                float inputs:opacity = 0.2
                token outputs:surface
            }
        }
        def Material "metal"
        {
            token outputs:surface.connect = </root/mtl/metal/pbr.outputs:surface>
            def Shader "pbr"
            {
                uniform token info:id = "UsdPreviewSurface"
                float inputs:opacity = 1.0
                token outputs:surface
            }
        }
    }
    def Mesh "a" ( prepend apiSchemas = ["MaterialBindingAPI"] )
    {
        rel material:binding = </root/mtl/glass>
        point3f[] points = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
        int[] faceVertexCounts = [3]
        int[] faceVertexIndices = [0, 1, 2]
        uniform token subdivisionScheme = "catmullClark"
    }
    def Mesh "b" ( prepend apiSchemas = ["MaterialBindingAPI"] )
    {
        rel material:binding = </root/mtl/metal>
        int[] faceVertexCounts = [4]
    }
    def Xform "c"
    {
    }
}
"""


@pytest.fixture
def stage(tmp_path):
    Usd = pytest.importorskip("pxr.Usd")
    f = tmp_path / "s.usda"
    f.write_text(SCENE)
    return Usd.Stage.Open(str(f), Usd.Stage.LoadNone)


def _edges(g, kind):
    return {(e["source"], e["target"]) for e in g["edges"] if e["kind"] == kind}


# -- tier 1: MaterialBindingKind (auto, native) -----------------------------

def test_material_binding_auto_derives(stage):
    from weft import threadgraph
    g = threadgraph.build_graph(stage)      # default registry -> kind is auto
    # the fixture binds all-purpose, which resolves as the fallback for every
    # purpose, so it surfaces under the `full` lens (and preview).
    assert "usd:material:binding:full" in g["kinds"]
    e = _edges(g, "usd:material:binding:full")
    assert ("/root/a", "material:/root/mtl/glass") in e
    assert ("/root/b", "material:/root/mtl/metal") in e
    # the unbound Xform (not even a gprim) contributes nothing
    assert not any(src == "/root/c" for src, _ in e)


# -- tier 2: opacity-finish deriver (declared rule) -------------------------

def test_opacity_finish_declared(stage):
    from weft import threadgraph
    from weft.kinds import load_kinds
    kinds = load_kinds([{
        "kind": "finish", "structure": "facet",
        "population": {"derive": {"builtin": "opacity-finish", "threshold": 0.999}},
    }])
    g = threadgraph.build_graph(stage, registry=kinds)
    e = _edges(g, "finish")
    assert ("/root/a", "finish:translucent") in e   # opacity 0.2 < 0.999
    assert ("/root/b", "finish:opaque") in e         # opacity 1.0
    assert not any(src == "/root/c" for src, _ in e)           # no material -> no finish


def test_opacity_finish_threshold_is_the_rule(stage):
    from weft import threadgraph
    from weft.kinds import load_kinds
    # a threshold below glass's 0.2 makes even glass "opaque" -- the judgment
    # lives in the declared rule, nothing is baked in.
    kinds = load_kinds([{
        "kind": "finish", "structure": "facet",
        "population": {"derive": {"builtin": "opacity-finish", "threshold": 0.1}},
    }])
    g = threadgraph.build_graph(stage, registry=kinds)
    e = _edges(g, "finish")
    assert ("/root/a", "finish:opaque") in e         # 0.2 not < 0.1


# -- data side: named-attribute columns -------------------------------------

def test_attr_column_scalar_and_none(stage):
    from weft import data
    tbl = data.project(stage, columns=["attr:subdivisionScheme"])
    rows = {r["path"]: r for r in tbl.rows()}
    assert rows["/root/a"]["attr:subdivisionScheme"] == "catmullClark"
    assert rows["/root/b"]["attr:subdivisionScheme"] is None    # unauthored


def test_attr_column_array_reports_length(stage):
    from weft import data
    tbl = data.project(stage, columns=["attr:points"])
    rows = {r["path"]: r for r in tbl.rows()}
    assert rows["/root/a"]["attr:points"] == 3                  # array -> length
    assert rows["/root/c"]["attr:points"] is None               # no points
