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


def _close_dangling(g: dict) -> dict:
    """Make a slice graph self-contained: a masked slice can carry edges whose
    other end is a prim OUTSIDE the slice (a shared material, the parent) --
    those are exactly the relationships worth seeing, but the viewer assumes
    every edge endpoint is a node and crashes (ADJ[undefined].push) on a
    dangling one. Add a light node for each missing endpoint so the edge
    resolves and the neighbor shows, labeled by its leaf name."""
    ids = {n["id"] for n in g.get("nodes", [])}
    extra = {}
    for e in g.get("edges", []):
        for ep in (e["source"], e["target"]):
            if ep not in ids and ep not in extra:
                leaf = ep.rsplit("/", 1)[-1] or ep
                extra[ep] = {"id": ep, "label": leaf, "type": "group", "deg": 0}
    if extra:
        g["nodes"].extend(extra.values())
    return g


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
        g = threadgraph.build_graph(masked)
        return _close_dangling(g)

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
        elif load:
            # no selection + load: an expensive whole-stage dimension (e.g.
            # organize-by material) the user explicitly asked to load for.
            self.stage.Load()
            self.loaded = True
        tbl = _data.project(self.stage, paths, columns=columns)
        return {"columns": tbl.names, "rows": tbl.rows()}

    def card(self, path: str) -> dict:
        """Everything the prim card shows for one prim: identity + cheap data +
        its relationships. Read-only, one prim. Returns {"error": ...} on a bad
        path rather than raising.

        Relationships: registry kinds have no per-prim edge API (they contribute
        via a whole-stage walk + populate), so derived edges come from the slice
        graph of `path:<path>` (edges whose source is this prim); native
        authored relationships are read straight off the prim."""
        from .. import data as _data
        prim = self.stage.GetPrimAtPath(path) if path else None
        if not prim or not prim.IsValid():
            return {"error": "no prim at %s" % (path or "<empty>")}
        tbl = _data.project(
            self.stage, [path],
            columns=["type", "has_payload", "bbox_volume",
                     "centroid_x", "centroid_y", "centroid_z"])
        rows = tbl.rows()
        row = rows[0] if rows else {}
        # Scalar/short attrs only: a mesh's `points`/`faceVertexIndices` are
        # arrays of millions of floats -- stringifying them would dump megabytes
        # into the card. Show the kind of metadata a reader scans (purpose,
        # subdivisionScheme, a primvar value), summarise arrays as a count.
        attrs = {}
        for a in prim.GetAuthoredAttributes():
            try:
                v = a.Get()
                if v is None:
                    continue
                if hasattr(v, "__len__") and not isinstance(v, str):
                    attrs[a.GetName()] = "[%d values]" % len(v)
                else:
                    s = str(v)
                    attrs[a.GetName()] = s if len(s) <= 120 else s[:117] + "…"
            except Exception:
                pass
        rels, seen = [], set()

        def add(kind, target):
            if (kind, target) not in seen:
                seen.add((kind, target))
                rels.append({"kind": kind, "target": target})

        # Bound materials the inheritance-aware way: ComputeBoundMaterial per
        # purpose resolves a binding authored on an ancestor or via a collection,
        # which the prim's own authored rels and a subtree slice both miss. (It
        # needs the prim loaded -- bindings sit behind payloads -- but a prim
        # that isn't loaded here doesn't compose, so we never reach this for one.)
        try:
            from pxr import UsdShade
            api = UsdShade.MaterialBindingAPI(prim)
            for purpose in ("full", "preview"):
                mat, _rel = api.ComputeBoundMaterial(getattr(UsdShade.Tokens, purpose))
                if mat and mat.GetPrim() and mat.GetPrim().IsValid():
                    add("material:binding:" + purpose, mat.GetPath().pathString)
        except Exception:
            pass
        for r in prim.GetAuthoredRelationships():
            for t in r.GetTargets():
                add(r.GetName(), str(t))
        cx, cy, cz = (row.get("centroid_x"), row.get("centroid_y"),
                      row.get("centroid_z"))
        return {
            "path": path,
            "type": prim.GetTypeName() or row.get("type") or "",
            "payload": bool(row.get("has_payload")),
            "bbox_volume": row.get("bbox_volume"),
            "centroid": None if cx is None else [cx, cy, cz],
            "attrs": attrs,
            "relationships": rels,
        }

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

    # -- kept sets (keep a set; tell me when it moves) -------------------------

    def _kept_dir(self) -> str:
        from .. import kept as _kept
        if not hasattr(self, "_kd"):
            self._kd = _kept.kept_dir(os.path.dirname(os.path.abspath(self.context)))
        return self._kd

    def keep(self, name: str, expression: str) -> dict:
        from .. import kept as _kept
        try:
            name = (name or "").strip()
            if not name:
                return {"error": "a kept set needs a name"}
            rec = _kept.capture(self.stage, self.context, expression, name)
            rec["context"] = os.path.abspath(self.context)
            _kept.save(rec, self._kept_dir())
            return {"name": name, "expression": expression,
                    "count": len(rec["members"])}
        except Exception as e:
            return {"error": str(e)}

    def _check(self, name: str) -> dict:
        from .. import kept as _kept
        try:
            rec = _kept.load(name, self._kept_dir())
        except Exception:
            return {"error": "no kept set named '%s'" % name}
        rep = _kept.check(rec, self.stage, self.context)
        rep["name"] = rec.get("name", name)
        rep["expression"] = rec.get("expression", "")
        rep["created"] = rec.get("created", "")
        return rep

    def kept(self) -> list:
        from .. import kept as _kept
        out = []
        try:
            names = _kept.list_kept(self._kept_dir())
        except Exception:
            return out
        for n in names:
            rep = self._check(n)
            if rep.get("error"):
                # a set that can't be checked (bad expression, unreadable file)
                out.append({"name": n, "expression": rep.get("expression", ""),
                            "state": "unknown", "counts": {}, "error": rep["error"]})
                continue
            out.append({"name": rep["name"], "expression": rep["expression"],
                        "state": "holds" if rep["holds"] else "moved",
                        "counts": rep["counts"]})
        return out

    def check_one(self, name: str) -> dict:
        return self._check(name)

    def forget(self, name: str) -> dict:
        from .. import kept as _kept
        if _kept.forget(name, self._kept_dir()):
            return {"forgot": name}
        return {"error": "no kept set named '%s'" % name}


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
                elif path == "/card":
                    c = state.card(q.get("path", ""))
                    self._json(c, 400 if "error" in c else 200)
                elif path == "/data":
                    cols = q["columns"].split(",") if q.get("columns") else None
                    self._json(state.data(cols, q.get("select"),
                                          load=q.get("load") == "1"))
                elif path == "/kept":
                    self._json(state.kept())
                elif path == "/check":
                    d = state.check_one(q.get("name", ""))
                    self._json(d, 400 if "error" in d and "holds" not in d else 200)
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
                elif path == "/keep":
                    r = state.keep(body.get("name", ""), body.get("expression", ""))
                    self._json(r, 400 if "error" in r else 200)
                elif path == "/forget":
                    r = state.forget(body.get("name", ""))
                    self._json(r, 400 if "error" in r else 200)
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
