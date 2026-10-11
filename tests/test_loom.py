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


def test_expression_bar_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="expr"' in html
        assert b"no slice expression yet" in html   # the coverage caption
    finally:
        httpd.shutdown()


def test_slice_bar_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="slicebar"' in html
        assert b"keep this set" in html          # the slice bar keeps, not locks
    finally:
        httpd.shutdown()


def test_card_drawer_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b'id="card"' in html
        assert b"view as graph" in html
    finally:
        httpd.shutdown()


def test_card_binding_is_inheritance_aware(ctx):
    # the card resolves bound material via ComputeBoundMaterial, so a binding
    # the prim doesn't author itself still shows (the fixture authors it here,
    # but the path is the inheritance-aware one, not a subtree slice).
    from weft.loom import LoomState
    st = LoomState(ctx, load=True)
    c = st.card("/root/bench/a")
    kinds = {r["kind"] for r in c["relationships"]}
    assert "material:binding:full" in kinds


def test_material_metric(ctx):
    # the expensive `material` column: bound material (full) as a path, loaded
    from weft import data as _data
    from pxr import Usd
    stage = Usd.Stage.Open(ctx, Usd.Stage.LoadAll)
    tbl = _data.project(stage, ["/root/bench/a"], columns=["material"])
    assert tbl.rows()[0]["material"] == "/root/bench/mtl/glass"


def test_loom_kept_endpoints(ctx, tmp_path, monkeypatch):
    from weft.loom import LoomState
    monkeypatch.chdir(tmp_path)                 # .weft/ lands here
    st = LoomState(ctx, load=True)
    assert "error" in st.keep("bad", "where:~~")          # honest, not a raise
    rec = st.keep("as", "name:a")
    assert rec["name"] == "as" and rec["count"] == 1
    ks = st.kept()
    assert [k["name"] for k in ks] == ["as"]
    assert ks[0]["state"] == "holds" and ks[0]["expression"] == "name:a"
    d = st.check_one("as")
    assert d["holds"] is True and d["expression"] == "name:a"
    assert "error" in st.check_one("nope")
    assert "error" in st.forget("nope")
    st.forget("as")
    assert st.kept() == []


def test_http_kept_routes(ctx, tmp_path, monkeypatch):
    from weft.loom import serve
    monkeypatch.chdir(tmp_path)
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = "http://127.0.0.1:%d" % port

    def post(path, obj):
        req = urllib.request.Request(base + path, data=json.dumps(obj).encode(),
                                     headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    try:
        assert post("/keep", {"name": "as", "expression": "name:a"})["count"] == 1
        ks = json.loads(urllib.request.urlopen(base + "/kept", timeout=10).read())
        assert ks[0]["name"] == "as" and ks[0]["state"] == "holds"
        d = json.loads(urllib.request.urlopen(base + "/check?name=as", timeout=10).read())
        assert d["holds"] is True
        assert post("/forget", {"name": "as"}).get("forgot") == "as"
    finally:
        httpd.shutdown()


def test_kept_ui_present(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b"keep this set" in html
        assert b'id="keptstrip"' in html
        assert b"re-check" in html
        assert b"certified" not in html and b"digest" not in html   # vocabulary scrub
    finally:
        httpd.shutdown()


def test_drop_collections_filters():
    from weft.loom.server import _drop_collections
    g = {"nodes": [{"id": "a", "type": "group"},
                   {"id": "c", "type": "collection"}],
         "edges": [{"source": "a", "target": "b", "kind": "usd:material:binding:full"},
                   {"source": "a", "target": "c", "kind": "usd:collection"}],
         "kinds": ["usd:material:binding:full", "usd:collection"]}
    d = _drop_collections(g)
    assert all("collection" not in e["kind"] for e in d["edges"])
    assert all(n["type"] != "collection" for n in d["nodes"])
    assert "usd:collection" not in d["kinds"]


def test_graph_toggle_and_autoload_markers(ctx):
    from weft.loom import serve
    httpd = serve(ctx, port=0, load=True, open_browser=False)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        html = urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=10).read()
        assert b"hide collections" in html              # graph toggle
        assert b"needs the scene loaded" in html         # material: auto-load prompt
    finally:
        httpd.shutdown()


def test_viewer_ships_inside_package():
    # the graph viewer must live inside weft/loom/ (covered by package-data
    # "weft.loom" = ["*.html"]) so a pip-installed Loom has its graph pane.
    import os
    import weft.loom.server as _srv
    pkg_viewer = os.path.join(os.path.dirname(_srv.__file__), "viewer_template.html")
    assert os.path.exists(pkg_viewer), "viewer_template.html missing from weft/loom/"
