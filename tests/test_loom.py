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
    def Scope "mtl"
    {
        def Material "glass"
        {
        }
    }
    def Xform "bench"
    {
        def Mesh "a" ( prepend apiSchemas = ["MaterialBindingAPI"] )
        {
            rel material:binding:full = </root/mtl/glass>
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


def test_static_export(ctx, tmp_path):
    from weft.loom import export
    out = str(tmp_path / "bundle")
    files = export(ctx, out, load=True)
    assert os.path.exists(os.path.join(out, "index.html"))
    assert os.path.exists(os.path.join(out, "profile.json"))
    pf = json.load(open(os.path.join(out, "profile.json")))
    assert pf["prims"] >= 1
