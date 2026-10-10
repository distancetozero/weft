"""The Loom server: a localhost, read-only "USD as data" surface over weft's
engine. Holds one open stage + the pull cache; serves a four-pane page and a
handful of JSON endpoints, each a thin wrapper over existing weft. No authoring,
no overlay, no edit target -- read, query, slice, certify.
"""
from __future__ import annotations

import json
import os
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional

# Above this many edges, the whole-scene graph is too large to ship to a
# browser (ALab is ~165k even unloaded). Shipping it would be the very
# "load the whole thing" the project rejects -- so on a large scene the graph
# pane invites you to query a focused slice instead. profile/table/query/pull
# are unaffected (they don't dump the whole graph).
GRAPH_EDGE_CAP = 6000

_HERE = os.path.dirname(os.path.abspath(__file__))
_VIEWER = os.path.join(os.path.dirname(_HERE), "..", "extras", "usdview",
                       "weftViewer", "viewer_template.html")


def _predicate(Usd):
    return Usd.TraverseInstanceProxies(
        Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _message_page(inner: str) -> str:
    return ("""<!doctype html><meta charset="utf-8">
<style>html{color-scheme:dark}body{margin:0;height:100vh;display:flex;
align-items:center;justify-content:center;background:#17140f;color:#a79b86;
font:14px/1.6 ui-sans-serif,system-ui,sans-serif;text-align:center}
div{max-width:30rem;padding:2rem}b{color:#f2d79a}code{color:#9db0c0}</style>
<div>%s</div>""" % inner)


def _too_large_page(nodes: int, edges: int) -> str:
    return _message_page(
        "<p><b>%d relationships</b> across %d nodes — too large to graph whole.</p>"
        "<p>That's the point of weft: don't load the world. <b>Click a prim in the "
        "table</b> (or query a slice) to explore from there.</p>" % (edges, nodes))


class LoomState:
    """One open stage + the engine calls behind each endpoint. Pure weft; no
    HTTP here, so it's testable directly."""

    def __init__(self, context: str, load: bool = False) -> None:
        from pxr import Usd
        self.context = context
        self._Usd = Usd
        self.stage = Usd.Stage.Open(
            context, Usd.Stage.LoadAll if load else Usd.Stage.LoadNone)
        if self.stage is None:
            raise ValueError("cannot open %s" % context)
        self.loaded = load

    # -- read -----------------------------------------------------------------

    def profile(self) -> dict:
        from . import server as _self  # noqa
        from .. import pull as _pull
        Usd = self._Usd
        prims = list(self.stage.Traverse(_predicate(Usd)))
        payloaded = sum(1 for p in prims if p.HasAuthoredPayloads())
        rels = _pull.authored_relationship_kinds(self.stage)
        g = self.graph()
        lens_counts = Counter(e["kind"] for e in g["edges"])
        return {
            "context": self.context,
            "loaded": self.loaded,
            "prims": len(prims),
            "payloaded": payloaded,
            "payloaded_pct": round(100.0 * payloaded / max(len(prims), 1), 1),
            "native_relationship_kinds": rels,
            "lenses": {k: lens_counts.get(k, 0) for k in g["kinds"]},
            "hint": ("most structure is behind payloads; open with --load to "
                     "see material/collection relationships"
                     if not self.loaded and payloaded else ""),
        }

    def graph(self) -> dict:
        from .. import threadgraph
        return threadgraph.build_graph(self.stage)

    def graph_capped(self) -> dict:
        """The full graph, or a summary when it's too large to ship whole."""
        g = self.graph()
        if len(g["edges"]) > GRAPH_EDGE_CAP:
            return {"truncated": True, "nodes": len(g["nodes"]),
                    "edges": len(g["edges"]), "kinds": g["kinds"]}
        return g

    def slice_graph(self, expression: str) -> dict:
        """The graph of just the SLICE an expression names: pull it, OpenMasked
        to that population, build_graph on the masked stage. Small and
        renderable even when the whole-scene graph is not -- this is how you
        explore a big scene: focus, then see. Cached pull under the hood."""
        from pxr import Usd
        from .. import compose as _compose, pull as _pull, threadgraph
        e = _compose.parse_expression(expression)
        p = _pull.pull(self.context, e.seeds, follow=e.follow, depth=e.depth,
                       cache=True)
        paths = [m.path for m in p.members]
        if not paths:
            return {"nodes": [], "edges": [], "kinds": [], "empty": True}
        masked = Usd.Stage.OpenMasked(self.context, Usd.StagePopulationMask(paths))
        masked.Load()
        return threadgraph.build_graph(masked)

    def data(self, columns: Optional[List[str]] = None,
             select: Optional[str] = None, load: bool = False) -> dict:
        from .. import data as _data
        from .. import ask as _ask
        Usd = self._Usd
        paths = None
        if select:
            res = _ask.resolve_seeds(self.stage, [select])
            paths = sorted({p for r in res for p in r.paths})
            if load:
                for p in paths:
                    self.stage.Load(p)
        tbl = _data.project(self.stage, paths, columns=columns)
        return {"columns": tbl.names, "rows": tbl.rows()}

    def query(self, expression: str) -> dict:
        from .. import compose as _compose
        from .. import pull as _pull
        e = _compose.parse_expression(expression)
        p = _pull.pull(self.context, e.seeds, follow=e.follow, depth=e.depth,
                       cache=True)
        return {"expression": expression,
                "members": sorted(m.path for m in p.members),
                "follow": list(p.follow)}

    def pull(self, expression: str, out: Optional[str] = None) -> dict:
        from .. import compose as _compose
        from .. import manifest as _manifest
        c = _compose.compose(self.context, expression, out=out, cache=True)
        _manifest.layer_hashes(c.pull)
        doc = _manifest.to_document(c.pull, str(self._Usd.GetVersion()))
        digest = _manifest.read_document(doc).get("digest")
        return {"expression": expression, "members": c.member_count,
                "prims": c.prim_count, "out": out, "digest": digest}

    # -- page assembly --------------------------------------------------------

    def viewer_html(self, expr: Optional[str] = None) -> str:
        if expr:
            g = self.slice_graph(expr)
            if g.get("empty"):
                return _message_page("nothing matched <b>%s</b>" % _esc(expr))
        else:
            g = self.graph()
        if len(g["edges"]) > GRAPH_EDGE_CAP:
            return _too_large_page(len(g["nodes"]), len(g["edges"]))
        tpl = open(_VIEWER).read()
        return tpl.replace("__DATA__", json.dumps(g).replace("</", "<\\/"))

    def app_html(self) -> str:
        return open(os.path.join(_HERE, "app.html")).read()


# -- static export (no server; shareable) ------------------------------------

def export(context: str, out_dir: str, load: bool = False) -> List[str]:
    """Write a self-contained, read-only bundle: the page + the JSON the live
    endpoints would return, so it opens with no server. Returns the files."""
    st = LoomState(context, load=load)
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for name, obj in (("profile.json", st.profile()),
                      ("data.json", st.data())):
        path = os.path.join(out_dir, name)
        with open(path, "w") as fh:
            json.dump(obj, fh)
        written.append(path)
    # viewer_html already guards large scenes; the app embeds it by file name.
    vpath = os.path.join(out_dir, "viewer.html")
    with open(vpath, "w") as fh:
        fh.write(st.viewer_html())
    written.append(vpath)
    apath = os.path.join(out_dir, "index.html")
    with open(apath, "w") as fh:
        fh.write(st.app_html()
                 .replace("/* STATIC */", "window.LOOM_STATIC=true;")
                 .replace('src="viewer"', 'src="viewer.html"'))
    written.append(apath)
    return written


# -- the HTTP transport -------------------------------------------------------

def _make_handler(state: LoomState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj))

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            q = {}
            if "?" in self.path:
                from urllib.parse import parse_qs
                q = {k: v[0] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
            try:
                if path == "/":
                    self._send(200, state.app_html(), "text/html; charset=utf-8")
                elif path == "/viewer":
                    self._send(200, state.viewer_html(q.get("expr")),
                               "text/html; charset=utf-8")
                elif path == "/profile":
                    self._json(state.profile())
                elif path == "/graph":
                    self._json(state.graph_capped())
                elif path == "/data":
                    cols = q["columns"].split(",") if q.get("columns") else None
                    self._json(state.data(cols, q.get("select"),
                                          load=q.get("load") == "1"))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:  # never 500 the whole server on one bad call
                self._json({"error": str(e)}, 400)

        def do_POST(self):
            path = self.path.split("?", 1)[0]
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n) or b"{}") if n else {}
            try:
                if path == "/query":
                    self._json(state.query(body["expression"]))
                elif path == "/pull":
                    self._json(state.pull(body["expression"], body.get("out")))
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._json({"error": str(e)}, 400)

    return Handler


def serve(context: str, port: int = 8765, load: bool = False,
          open_browser: bool = True):
    """Start the Loom on 127.0.0.1:<port>. Returns the server (call
    serve_forever) -- the CLI runs it; tests drive it on a thread."""
    state = LoomState(context, load=load)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), _make_handler(state))
    if open_browser:
        import webbrowser
        webbrowser.open("http://127.0.0.1:%d/" % httpd.server_address[1])
    return httpd
