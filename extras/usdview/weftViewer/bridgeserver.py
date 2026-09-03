#
# The "Weft Threads" browser viewer: the plugin starts a LOOPBACK-ONLY,
# TOKEN-GATED local HTTP server and opens the owner's own browser to
# weft's tuned d3 thread viewer (viewer_template.html), bridged to the
# LIVE usdview stage over that server -- a node click in the browser loads
# that prim's geometry and moves usdview's own selection, cross-process.
#
# Why a browser window and not embedded in usdview itself: QtWebEngine
# (Chromium embedded in usdview's own OpenGL-composited main window)
# crashed the real usdview GUI on macOS, confirmed by direct interactive
# testing (see .superpowers/threadpanel-report.md). A follow-up native-Qt
# rebuild (threadpanel.py) survived but couldn't reproduce the polished d3
# viewer's own lens selector / weft-ask bar / inspector / back-home
# interaction -- reimplementing all of that in QGraphicsView was assessed
# as not worth it against just running the ALREADY-BUILT, ALREADY-LIKED d3
# viewer in its native habitat (a real browser), with usdview as a live
# data source over HTTP instead of an embedded QWebChannel. A real
# browser's own renderer is a separate OS process; nothing here ever touches
# usdview's own OpenGL surface.
#
# SECURITY (this is a real local HTTP server, treated accordingly):
#   - Bound to 127.0.0.1 ONLY (see _BridgeServer.__init__ -- never
#     0.0.0.0), an OS-assigned ephemeral port (bind port 0, read back
#     server_address[1]) -- ordinary port scanning finds nothing, and the
#     port isn't reachable from another machine at all.
#   - A random per-session token (secrets.token_urlsafe(32)) is embedded in
#     the URL the plugin opens (?t=TOKEN) and required, via query param or
#     the X-Weft-Token header, compared with hmac.compare_digest (constant-
#     time), on EVERY page/API request; a missing or wrong token gets a
#     bare 403, nothing else. This is what stops another local process (or
#     a stray browser tab from a past session) from talking to the bridge.
#   - Exactly four routes exist, all hardcoded string comparisons in
#     `_Handler` -- "/", "/graph.json", POST "/select", POST "/load" --
#     plus a small hardcoded dict of vendored asset paths (`_load_assets`).
#     There is no dynamic filesystem-path-to-file mapping anywhere in this
#     module, so there is no path-traversal surface to have a bug in.
#   - d3.min.js is vendored into extras/usdview/weftViewer/assets/ and
#     served from this process; the Google Fonts <link> is dropped entirely
#     (the CSS already declares a solid system-font fallback stack) rather
#     than vendoring font binaries for a purely decorative upgrade. The
#     served page makes ZERO external network calls.
#   - The server is shut down via `atexit` (registered the moment it
#     starts). There is no "container destroyed" hook in the existing
#     usdview plugin framework to hang a cleaner teardown off of, so
#     `atexit` -- ordinary process exit -- is the mechanism; a hard crash
#     of usdview itself wouldn't run it (the daemon thread would just die
#     with the process either way, which is the actual concern this
#     module needs to avoid causing, not a case atexit needs to cover).
#
# THREADING (the actual hard part, given this branch's whole crash
# history): the HTTP server runs its own request-handling threads
# (ThreadingHTTPServer). `stage.Load()`, selection changes, and even
# read-only `build_graph()` calls MUST run on usdview's own Qt main
# thread -- never off it. `_MainThreadBridge` is a QObject constructed on
# the main thread (inside `open_browser_viewer`, itself a plugin command
# callback); its `select_blocking`/`load_blocking`/`graph_blocking`
# methods, called from a REQUEST-HANDLING thread, emit a Qt signal with a
# small "done" object (a `threading.Event` + a result dict) as an extra
# argument, then block on that event. Because the emitting thread differs
# from the QObject's own (main) thread, Qt's default AutoConnection
# becomes a QUEUED connection automatically -- the actual slot body runs
# on the main thread's event loop, on its own next idle turn, and sets the
# event when done, waking the waiting request thread back up to write the
# HTTP response. No pxr/usdviewApi call happens anywhere except inside
# those three slot bodies, all decorated to run main-thread-only by
# construction (the queued-connection mechanism, not a comment promising
# discipline).
#
from __future__ import annotations

import atexit
import hmac
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.parse
import webbrowser

try:
    from pxr.Usdviewq.qt import QtCore
except ImportError as _e:
    print("weftViewer.bridgeserver: pxr.Usdviewq.qt unavailable (%s); the Weft "
          "Threads browser viewer cannot be built outside usdview" % _e, file=sys.stderr)
    QtCore = None

from . import _stagebridge

_HERE = os.path.dirname(__file__)
_VIEWER_TEMPLATE = os.path.join(_HERE, "viewer_template.html")
_ASSETS_DIR = os.path.join(_HERE, "assets")

# Exact strings the served HTML gets rewritten from -- CDN references in
# the template (kept there so the file still works as a standalone,
# offline-irrelevant demo opened directly from disk/a plain static server)
# become local, vendored/removed ones for the live, token-gated serve.
_CDN_D3_TAG = '<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>'
_LOCAL_D3_TAG = '<script src="/assets/d3.min.js"></script>'
_FONTS_LINK_TAG = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
                    'family=Fraunces:opsz,wght@9..144,600&family=Inter:wght@400;500;600'
                    '&display=swap">')

_ASSET_FILES = {
    "/assets/d3.min.js": ("d3.min.js", "application/javascript; charset=utf-8"),
}


def _safe_json(data):
    """json.dumps, with "</" escaped to "<\\/" -- otherwise a prim path or
    label that happened to contain "</" could prematurely close the
    surrounding <script> tag this gets embedded in. Flagged in review;
    applied here at the one place JSON is embedded INTO an HTML <script>
    block (the /graph.json HTTP response is never HTML-embedded, so it
    doesn't need this -- plain json.dumps there)."""
    return json.dumps(data).replace("</", "<\\/")


def _render_html(graph_data):
    with open(_VIEWER_TEMPLATE, "r", encoding="utf-8") as fh:
        html = fh.read()
    html = html.replace(_CDN_D3_TAG, _LOCAL_D3_TAG)
    html = html.replace(_FONTS_LINK_TAG, "")
    html = html.replace("__DATA__", _safe_json(graph_data))
    return html


def _load_assets():
    """Reads every vendored asset off disk ONCE, into a fixed dict the
    request handler only ever looks up by exact key -- no dynamic
    path-to-file mapping, so no path-traversal surface exists to review."""
    assets = {}
    for route, (filename, content_type) in _ASSET_FILES.items():
        with open(os.path.join(_ASSETS_DIR, filename), "rb") as fh:
            assets[route] = (content_type, fh.read())
    return assets


# -- main-thread marshaling --------------------------------------------

def _make_main_thread_bridge_class():
    class _MainThreadBridge(QtCore.QObject):
        _selectSig = QtCore.Signal(str, object)
        _loadSig = QtCore.Signal(list, object)
        _graphSig = QtCore.Signal(object)

        def __init__(self, api, parent=None):
            super().__init__(parent)
            self.api = api
            self._selectSig.connect(self._on_select)
            self._loadSig.connect(self._on_load)
            self._graphSig.connect(self._on_graph)

        # -- slots: run on the MAIN thread only (queued-connection dispatch) --

        def _on_select(self, path, done):
            try:
                _stagebridge.select_and_load(self.api, path)
                done["ok"] = True
            except Exception as e:
                done["ok"] = False
                done["error"] = str(e)
                self.api.PrintStatus("Weft Threads: /select failed: %s" % e)
            finally:
                done["event"].set()

        def _on_load(self, paths, done):
            try:
                _stagebridge.load_paths(self.api, paths)
                done["ok"] = True
            except Exception as e:
                done["ok"] = False
                done["error"] = str(e)
                self.api.PrintStatus("Weft Threads: /load failed: %s" % e)
            finally:
                done["event"].set()

        def _on_graph(self, done):
            try:
                from weft.threadgraph import build_graph
                done["data"] = build_graph(self.api.stage)
                done["ok"] = True
            except Exception as e:
                done["ok"] = False
                done["error"] = str(e)
            finally:
                done["event"].set()

        # -- called from a REQUEST-HANDLING thread; blocks until the main
        # thread's slot has actually run and set the event. -------------

        def _dispatch(self, signal, *args, timeout=15.0):
            done = {"event": threading.Event(), "ok": False}
            signal.emit(*args, done)
            finished = done["event"].wait(timeout)
            if not finished:
                done["ok"] = False
                done["error"] = "timed out waiting for usdview's main thread"
            return done

        def select_blocking(self, path, timeout=15.0):
            return self._dispatch(self._selectSig, path, timeout=timeout)

        def load_blocking(self, paths, timeout=15.0):
            return self._dispatch(self._loadSig, paths, timeout=timeout)

        def graph_blocking(self, timeout=15.0):
            return self._dispatch(self._graphSig, timeout=timeout)

    return _MainThreadBridge


# -- HTTP server ----------------------------------------------------------

class _Handler(http.server.BaseHTTPRequestHandler):
    server_version = "WeftThreadsBridge/1"

    def _token_ok(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        token = (qs.get("t") or [None])[0] or self.headers.get("X-Weft-Token")
        if not token:
            return False
        return hmac.compare_digest(token, self.server.token)

    def _send(self, code, body, content_type):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _forbidden(self):
        self._send(403, b"forbidden: missing or invalid token", "text/plain; charset=utf-8")

    def _not_found(self):
        self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path in self.server.assets:
            # Static, non-sensitive, hardcoded-whitelist files -- no token
            # needed (knowing their exact bytes carries no live-data risk,
            # and gating them would only complicate the <script>/<link>
            # tags that reference them for no security benefit).
            content_type, blob = self.server.assets[path]
            self._send(200, blob, content_type)
            return

        if path in ("/", "/index.html"):
            if not self._token_ok():
                return self._forbidden()
            self._send(200, self.server.html, "text/html; charset=utf-8")
            return

        if path == "/graph.json":
            if not self._token_ok():
                return self._forbidden()
            result = self.server.main_bridge.graph_blocking()
            if not result.get("ok"):
                self._send(500, json.dumps({"error": result.get("error", "unknown")}).encode(),
                           "application/json")
                return
            self._send(200, json.dumps(result["data"]).encode("utf-8"), "application/json")
            return

        self._not_found()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if not self._token_ok():
            return self._forbidden()

        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            self._send(400, b"bad json body", "text/plain; charset=utf-8")
            return

        if path == "/select":
            target = body.get("path")
            if not isinstance(target, str):
                self._send(400, b"missing 'path'", "text/plain; charset=utf-8")
                return
            result = self.server.main_bridge.select_blocking(target)
            self._send(200 if result.get("ok") else 500,
                       json.dumps({"ok": bool(result.get("ok")),
                                   "error": result.get("error")}).encode(),
                       "application/json")
            return

        if path == "/load":
            paths = body.get("paths")
            if not isinstance(paths, list):
                self._send(400, b"missing 'paths'", "text/plain; charset=utf-8")
                return
            result = self.server.main_bridge.load_blocking(paths)
            self._send(200 if result.get("ok") else 500,
                       json.dumps({"ok": bool(result.get("ok")),
                                   "error": result.get("error")}).encode(),
                       "application/json")
            return

        self._not_found()

    def log_message(self, fmt, *args):
        pass  # keep testusdview/console output clean; failures already
        # surface through api.PrintStatus from the main-thread slots.


class _BridgeServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, token, html, assets, main_bridge):
        # 127.0.0.1, never 0.0.0.0 -- loopback only, not reachable from any
        # other machine. Port 0 -> OS assigns an ephemeral free port,
        # read back via self.server_address[1] once bound.
        super().__init__(("127.0.0.1", 0), _Handler)
        self.token = token
        self.html = html
        self.assets = assets
        self.main_bridge = main_bridge


def _shutdown_server(server):
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass


# -- panel lifecycle ----------------------------------------------------

def open_browser_viewer(container, api):
    """Start the bridge server (first call) and open the browser to it;
    subsequent calls just reopen the browser to the already-running
    server's URL. Returns True once the browser open was attempted; on any
    failure to build the page or start the server, reports the exact
    error through `api.PrintStatus` and returns False."""
    existing = getattr(container, "_threadServer", None)
    if existing is not None:
        url = "http://127.0.0.1:%d/?t=%s" % (container._threadServerPort,
                                               container._threadServerToken)
        webbrowser.open(url)
        api.PrintStatus("Weft Threads: reopened the browser viewer (%s)" % url)
        return True

    if QtCore is None:
        api.PrintStatus("Weft Threads: BLOCKED -- pxr.Usdviewq.qt is unavailable "
                         "in this process")
        return False

    try:
        from weft.threadgraph import build_graph
        graph_data = build_graph(api.stage)
    except Exception as e:
        api.PrintStatus("Weft Threads: build_graph failed, opening an empty graph: %s" % e)
        graph_data = {"nodes": [], "edges": [], "kinds": []}

    try:
        html = _render_html(graph_data)
        assets = _load_assets()
    except OSError as e:
        api.PrintStatus("Weft Threads: could not load the viewer template/assets: %s" % e)
        return False

    token = secrets.token_urlsafe(32)
    bridge_cls = _make_main_thread_bridge_class()
    main_bridge = bridge_cls(api)

    try:
        server = _BridgeServer(token, html, assets, main_bridge)
    except OSError as e:
        api.PrintStatus("Weft Threads: BLOCKED -- could not start the local bridge "
                         "server: %s" % e)
        return False

    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever,
                               name="weft-threads-bridge", daemon=True)
    thread.start()
    atexit.register(_shutdown_server, server)

    # Held on the container (the WeftViewerContainer instance, which
    # outlives this call) so nothing here is garbage-collected out from
    # under the running server thread / the browser's live connection.
    container._threadServer = server
    container._threadServerThread = thread
    container._threadServerToken = token
    container._threadServerPort = port
    container._threadMainBridge = main_bridge

    url = "http://127.0.0.1:%d/?t=%s" % (port, token)
    webbrowser.open(url)

    api.PrintStatus("Weft Threads: browser viewer open at %s (%d nodes)"
                     % (url, len(graph_data.get("nodes", []))))
    return True
