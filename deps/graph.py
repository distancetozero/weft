"""The dependency graph: build it once, query it in microseconds.

Two things here that USD cannot do on its own.

**Resolving namespace edges.** A `material:binding` names a prim path, not a
file. Turning that into a dependency means knowing which layer *defines* that
prim, so the graph indexes definitions first and resolves edges second.

**The reverse direction.** USD only ever knows what a layer points at. Nothing
in it can answer "what points at me" -- which is the question people actually
ask before republishing something. Reverse adjacency is built here, and it is
the reason this exists.

Cost, measured on 1000 assets x 300 prims (57 MB, 600k edges):

    full build      23-36 s     once
    one asset       23 ms       on republish
    cached graph    49 KB
    reverse query   89 us       -> 593 dependents
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .walk import ARC, ASSET_ATTR, Edge, LayerRecord, walk_file

CACHE_VERSION = 1


@dataclass
class Unresolved:
    """An edge whose target nothing on disk defines.

    Read this carefully, because the obvious interpretation is wrong. An
    unresolved edge is dangling *in the layer that authored it*, which is not
    the same as dangling in a composed scene.

    The common benign case, confirmed against real published assets: a geo
    layer exported from a DCC carries `material:binding -> /Materials/Steel`,
    a path that layer does not define. The asset layer above it references the
    geo and *overrides* the binding with the correct in-context path. Composed,
    everything binds; in isolation the geo layer looks broken.

    So `shadowable` is the signal that matters. If something references this
    layer, a stronger opinion may already fix the edge. If nothing does, there
    is nothing above it to fix anything.
    """
    source: str
    src_prim: str
    kind: str
    name: str
    target: str
    shadowable: bool = True   # is this layer referenced by anything?


@dataclass
class Graph:
    records: Dict[str, LayerRecord] = field(default_factory=dict)
    # file -> files it depends on, and the inverse
    forward: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    reverse: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    # prim path -> layers defining it
    defines: Dict[str, Set[str]] = field(default_factory=lambda: defaultdict(set))
    unresolved: List[Unresolved] = field(default_factory=list)
    # (source layer, target prim path, candidate layers) -- a namespace edge
    # several unrelated layers could satisfy. Reported, never guessed at.
    ambiguous: List[Tuple[str, str, List[str]]] = field(default_factory=list)
    # Layers that would not open. Any real tree has some.
    unreadable: List[str] = field(default_factory=list)
    build_seconds: float = 0.0

    # -- queries ----------------------------------------------------------

    def needs(self, ident: str, depth: Optional[int] = None) -> Set[str]:
        """Everything `ident` depends on, transitively. The pull closure."""
        return _closure(ident, self.forward, depth)

    def dependents(self, ident: str, depth: Optional[int] = None) -> Set[str]:
        """Everything that depends on `ident`. What breaks if you republish it."""
        return _closure(ident, self.reverse, depth)

    def direct_needs(self, ident: str) -> Set[str]:
        return set(self.forward.get(ident, ()))

    def split(self, paths: Iterable[str]) -> Tuple[Set[str], Set[str]]:
        """Separate USD layers from other assets a closure pulls in.

        An asset-valued attribute points at a texture or a point cache as
        legitimately as a reference points at a layer, and both are real
        dependencies -- but they are not the same thing. On a production scene
        a single asset's closure is a handful of layers and two thousand PNGs,
        so reporting one number for both is meaningless.
        """
        layers, assets = set(), set()
        for p in paths:
            (layers if p in self.records else assets).add(p)
        return layers, assets

    def direct_dependents(self, ident: str) -> Set[str]:
        return set(self.reverse.get(ident, ()))

    def why(self, src: str, dst: str) -> List[Edge]:
        """The specific edges in `src` that reach `dst`.

        Answers "why does this depend on that" with the authored opinion, not
        just a yes.
        """
        rec = self.records.get(src)
        if not rec:
            return []
        return [e for e in rec.edges if e.resolved == dst]

    def path_between(self, src: str, dst: str) -> List[str]:
        """A shortest dependency chain from src to dst, or [] if none."""
        if src == dst:
            return [src]
        prev, q = {src: None}, deque([src])
        while q:
            node = q.popleft()
            for nxt in self.forward.get(node, ()):
                if nxt in prev:
                    continue
                prev[nxt] = node
                if nxt == dst:
                    chain, cur = [], dst
                    while cur is not None:
                        chain.append(cur)
                        cur = prev[cur]
                    return list(reversed(chain))
                q.append(nxt)
        return []

    def roots(self) -> List[str]:
        """Layers nothing else references -- shots, assemblies, entry points."""
        return sorted(i for i in self.records if not self.reverse.get(i))

    def leaves(self) -> List[str]:
        return sorted(i for i in self.records if not self.forward.get(i))

    def stats(self) -> Dict[str, int]:
        return {
            "layers": len(self.records),
            "specs": sum(r.n_specs for r in self.records.values()),
            "edges": sum(len(r.edges) for r in self.records.values()),
            "resolved_edges": sum(len(v) for v in self.forward.values()),
            "unresolved": len(self.unresolved),
        }


def _closure(start: str, adj: Dict[str, Set[str]], depth: Optional[int]) -> Set[str]:
    seen: Set[str] = set()
    q = deque([(start, 0)])
    while q:
        node, d = q.popleft()
        if depth is not None and d >= depth:
            continue
        for nxt in adj.get(node, ()):
            if nxt not in seen:
                seen.add(nxt)
                q.append((nxt, d + 1))
    return seen


# -- building ---------------------------------------------------------------

def _norm(path: str) -> str:
    return os.path.normpath(os.path.abspath(path))


def _resolve_asset(edge_target: str, from_layer: str) -> Optional[str]:
    """An asset path, relative to the layer that authored it."""
    if edge_target.startswith("/"):
        cand = edge_target
    else:
        cand = os.path.join(os.path.dirname(from_layer), edge_target)
    cand = _norm(cand)
    return cand if os.path.exists(cand) else None


def _longest_defining_prefix(prim_path: str, defines: Dict[str, Set[str]]) -> Set[str]:
    """Which layers define this prim, or its closest defined ancestor.

    A binding to `/World/Looks/Steel/shader` should resolve even when only
    `/World/Looks/Steel` is a defined prim, so walk up the namespace until
    something matches.
    """
    p = prim_path
    while p and p != "/":
        if p in defines:
            return defines[p]
        p = p.rsplit("/", 1)[0] or "/"
    return defines.get("/", set())


def build(paths: Sequence[str], cache: Optional["Cache"] = None,
          progress=None) -> Graph:
    """Walk every layer, index definitions, then resolve edges to files."""
    t0 = time.perf_counter()
    g = Graph()

    # Pass 1 -- walk, reusing anything the cache still vouches for.
    for i, p in enumerate(paths):
        ident = _norm(p)
        rec = cache.get(ident) if cache else None
        if rec is None:
            rec = walk_file(ident)
            if rec is None:
                g.unreadable.append(ident)
                continue
            rec.identifier = ident
            if cache:
                cache.put(rec)
        g.records[ident] = rec
        for prim in rec.defines:
            g.defines[prim].add(ident)
        if progress:
            progress(i + 1, len(paths))

    # Pass 2 -- asset edges. These carry a file path, so they resolve on their
    # own and establish each layer's composition context for pass 3.
    for ident, rec in g.records.items():
        for edge in rec.edges:
            if not edge.is_asset_edge:
                continue
            target = _resolve_asset(edge.target, ident)
            edge.resolved = target
            if target is None:
                g.unresolved.append(Unresolved(
                    ident, edge.src_prim, edge.kind, edge.name, edge.target))
            elif target != ident:
                g.forward[ident].add(target)
                g.reverse[target].add(ident)

    # Pass 3 -- namespace edges. A prim path only means something inside a
    # composition, and component assets conventionally share one namespace:
    # </World/Looks/metal> is defined by every asset in the library. Resolving
    # such a path against a global index invents dependencies between assets
    # that have nothing to do with each other, so narrow it in three steps.
    for ident, rec in g.records.items():
        context = _closure(ident, g.forward, None)   # what this layer composes
        for edge in rec.edges:
            if edge.is_asset_edge:
                continue

            # 1. Defined right here. An intra-layer edge, not a dependency.
            if _defined_locally(edge.target, rec):
                edge.resolved = ident
                continue

            owners = {o for o in _longest_defining_prefix(edge.target, g.defines)
                      if o != ident}
            if not owners:
                g.unresolved.append(Unresolved(
                    ident, edge.src_prim, edge.kind, edge.name, edge.target))
                continue

            # 2. Defined by something this layer actually composes. The only
            #    reading that corresponds to a real composition.
            in_context = owners & context
            if len(in_context) == 1:
                target = next(iter(in_context))
            elif in_context:
                target = sorted(in_context)[0]
                g.ambiguous.append((ident, edge.target, sorted(in_context)))
            elif len(owners) == 1:
                # 3. Exactly one candidate anywhere. Fair to take it.
                target = next(iter(owners))
            else:
                # Several unrelated layers define this path and none is in
                # context. Guessing here is what produced phantom edges, so
                # record the ambiguity instead of inventing one.
                g.ambiguous.append((ident, edge.target, sorted(owners)))
                continue

            edge.resolved = target
            g.forward[ident].add(target)
            g.reverse[target].add(ident)

    # Pass 3 -- an unresolved edge in a layer nothing references has nothing
    # above it that could override the edge. Those are the ones worth reading.
    for u in g.unresolved:
        u.shadowable = bool(g.reverse.get(u.source))

    g.build_seconds = time.perf_counter() - t0
    return g


def _defined_locally(prim_path: str, rec: LayerRecord) -> bool:
    defined = set(rec.defines)
    p = prim_path
    while p and p != "/":
        if p in defined:
            return True
        p = p.rsplit("/", 1)[0] or "/"
    return False


def discover(root: str, patterns=("*.usd", "*.usda", "*.usdc")) -> List[str]:
    base = Path(root)
    if base.is_file():
        return [str(base)]
    out: List[str] = []
    for pat in patterns:
        out.extend(str(p) for p in base.rglob(pat))
    return sorted(set(out))


# -- cache ------------------------------------------------------------------

class Cache:
    """Per-layer walk results, invalidated by mtime and size.

    Invalidation is per-asset because an asset's edges change only when that
    asset is rewritten. So a publish hook re-walks one file in ~23 ms and the
    graph stays true, rather than the whole index going stale at once.
    """

    def __init__(self, path: str):
        self.path = path
        self._data: Dict[str, LayerRecord] = {}
        self.hits = 0
        self.misses = 0
        self._load()

    def _load(self) -> None:
        try:
            with open(self.path) as fh:
                blob = json.load(fh)
        except (OSError, ValueError):
            return
        if blob.get("version") != CACHE_VERSION:
            return
        for ident, rec in blob.get("records", {}).items():
            try:
                self._data[ident] = LayerRecord.from_dict(rec)
            except TypeError:
                continue  # written by an older shape; just re-walk it

    def get(self, ident: str) -> Optional[LayerRecord]:
        rec = self._data.get(ident)
        if rec is None:
            self.misses += 1
            return None
        try:
            st = os.stat(ident)
        except OSError:
            self.misses += 1
            return None
        if st.st_mtime != rec.mtime or st.st_size != rec.size:
            self.misses += 1
            return None
        self.hits += 1
        return rec

    def put(self, rec: LayerRecord) -> None:
        self._data[rec.identifier] = rec

    def save(self) -> None:
        tmp = "%s.tmp-%d" % (self.path, os.getpid())
        payload = {
            "version": CACHE_VERSION,
            "records": {k: v.to_dict() for k, v in self._data.items()},
        }
        d = os.path.dirname(self.path)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, self.path)
