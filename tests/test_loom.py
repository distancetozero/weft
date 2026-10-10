"""The Loom server (read-only): LoomState endpoints + the HTTP contract, driven
without a browser. pxr-gated."""
import json
import os
import threading
import urllib.request

import pytest

SCENE = """#usda 1.0
( defaultPrim = "root" )
def Xform "root"
{
    def Xform "bench"
    {
        def Scope "mtl"
        {
            def Material "glass"
            {
            }
        }
        def Mesh "a" ( prepend apiSchemas = ["MaterialBindingAPI"] )
        {
            rel material:binding:full = </root/bench/mtl/glass>
            custom rel electrical:feeds = </root/bench>
            point3f[] points = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
        }
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    pytest.importorskip("pxr.Usd")
    f = tmp_path / "scene.usda"
    f.write_text(SCENE)
    return str(f)


def test_state_endpoints(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)

    pf = st.profile()
    assert pf["prims"] >= 1
    assert "material:binding:full" in pf["native_relationship_kinds"]
    assert "electrical:feeds" in pf["native_relationship_kinds"]

    g = st.graph()
    assert "nodes" in g and "edges" in g and "kinds" in g

    d = st.data(columns=["type"])
    assert "path" in d["columns"]
    assert any(r["path"] == "/root/bench/a" for r in d["rows"])

    q = st.query("name:a")
    assert "/root/bench/a" in q["members"]

    p = st.pull("name:a")
    assert p["members"] >= 1 and p["digest"]


def test_http_contract_and_localhost_bind(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    assert httpd.server_address[0] == "127.0.0.1"          # localhost only
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        prof = json.loads(urllib.request.urlopen(
            "http://127.0.0.1:%d/profile" % port, timeout=10).read())
        assert prof["prims"] >= 1

        req = urllib.request.Request(
            "http://127.0.0.1:%d/query" % port,
            data=json.dumps({"expression": "name:a"}).encode(),
            headers={"Content-Type": "application/json"})
        q = json.loads(urllib.request.urlopen(req, timeout=10).read())
        assert "/root/bench/a" in q["members"]

        # the app shell + reused viewer both serve
        assert b"weft" in urllib.request.urlopen(
            "http://127.0.0.1:%d/" % port, timeout=10).read()
    finally:
        httpd.shutdown()


def test_slice_graph_focuses(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    g = st.slice_graph("name:bench")           # explore the asset -> its slice
    assert not g.get("empty")
    touches_a = any(e["source"] == "/root/bench/a" or e["target"] == "/root/bench/a"
                    for e in g["edges"])
    assert touches_a                            # the slice includes the mesh's material edge
    empty = st.slice_graph("name:does_not_exist")
    assert empty.get("empty")


def test_static_export(ctx, tmp_path):
    from weft.loom import export
    out = str(tmp_path / "bundle")
    files = export(ctx, out, load=True)
    assert os.path.exists(os.path.join(out, "index.html"))
    assert os.path.exists(os.path.join(out, "profile.json"))
    pf = json.load(open(os.path.join(out, "profile.json")))
    assert pf["prims"] >= 1


def test_card(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    c = st.card("/root/bench/a")
    assert c["path"] == "/root/bench/a"
    assert c["type"] == "Mesh"
    kinds = {r["kind"] for r in c["relationships"]}
    targets = {r["target"] for r in c["relationships"]}
    assert any("material:binding" in k for k in kinds)
    assert "/root/bench/mtl/glass" in targets
    assert "electrical:feeds" in kinds            # native rel surfaces too
    assert "/root/bench" in targets


def test_card_bad_path(ctx):
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    c = st.card("/does/not/exist")
    assert "error" in c


def test_gui_target_expressions_resolve(ctx):
    from weft import compose as _compose, pull as _pull
    # every shape the pivot UI emits (Task 6 mapping) must be valid weft-ask
    exprs = [
        "path:/root/bench/a",
        "name:a",
        "name:a*",
        "where:bbox_volume>0",
        "where:bbox_volume>=0",
    ]
    for e in exprs:
        parsed = _compose.parse_expression(e)
        p = _pull.pull(ctx, parsed.seeds, follow=parsed.follow,
                       depth=parsed.depth, cache=False)
        assert p is not None            # parses and resolves, no raise
    parsed = _compose.parse_expression("where:purpose=render")
    assert parsed.seeds                 # parses even when nothing matches


def test_pivot_shell_serves(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b"organize-by" in html          # the pivot selector exists
        assert b'id="pivot"' in html            # the pivot table container
    finally:
        httpd.shutdown()


def test_organize_dimensions_offered(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        for v in (b'value="type"', b'value="payload"', b'value="material"'):
            assert v in html
    finally:
        httpd.shutdown()


def test_material_metric(ctx):
    # the expensive `material` column: bound material (full) as a path, loaded
    from weft import data as _data
    from pxr import Usd
    stage = Usd.Stage.Open(ctx, Usd.Stage.LoadAll)
    tbl = _data.project(stage, ["/root/bench/a"], columns=["material"])
    assert tbl.rows()[0]["material"] == "/root/bench/mtl/glass"
