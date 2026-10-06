"""The stage as data: a prim-level numeric projection (spec:
docs/superpowers/specs/2026-10-05-stage-as-data-c-prototype.md).

`project(stage, paths, columns)` returns a `Table` of one row per prim and one
column per deterministic metric -- the first query axis beyond structure/value/
relationship. Metrics split into two tiers:

  cheap     computable on a LoadNone stage without crossing any payload
            (type, has_payload, bbox_volume + centroid from extentsHint and the
            world transform -- the same pattern ask.resolve_seeds already uses).
  expensive need the prim's geometry loaded (point_count, poly_count, byte_cost);
            an uncomputed expensive metric is None, never a fabricated 0.

The core (registry, parsing helpers, Table.rows/csv/json) is pure Python so the
bare CI stays green; pxr is imported lazily inside project(), and numpy/pyarrow
are imported lazily inside the Table.to_* methods that need them.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# -- the metric registry (pure data; names importable without pxr) ----------

# cheap: no payload crossing. Numeric cheap metrics are the ones a grammar
# `where:<metric><op><n>` seed may select by (selection must never force a load).
CHEAP_METRICS: List[str] = [
    "type", "has_payload", "bbox_volume", "centroid_x", "centroid_y", "centroid_z",
]
EXPENSIVE_METRICS: List[str] = ["point_count", "poly_count", "byte_cost"]
METRIC_NAMES: List[str] = ["path"] + CHEAP_METRICS + EXPENSIVE_METRICS

# numeric cheap metrics -> selectable by a comparison predicate. type/has_payload
# are cheap but not numerically comparable, so they are not selectable in v1.
SELECTABLE_METRICS = {"bbox_volume", "centroid_x", "centroid_y", "centroid_z"}

_OPS = (">=", "<=", "==", "!=", ">", "<")


def compare(value: float, op: str, num: float) -> bool:
    if op == ">":  return value > num
    if op == "<":  return value < num
    if op == ">=": return value >= num
    if op == "<=": return value <= num
    if op == "==": return value == num
    if op == "!=": return value != num
    raise ValueError("unknown operator %r" % op)


# -- the table (pure-Python core; numpy/pyarrow optional) -------------------

@dataclass
class Table:
    names: List[str]
    _rows: List[Dict[str, Any]]

    def rows(self) -> List[Dict[str, Any]]:
        return list(self._rows)

    def __len__(self) -> int:
        return len(self._rows)

    def to_json(self, path: str) -> None:
        import json
        with open(path, "w") as fh:
            json.dump(self._rows, fh, indent=2, default=str)

    def to_csv(self, path: str) -> None:
        import csv
        with open(path, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=self.names)
            w.writeheader()
            for r in self._rows:
                w.writerow({k: ("" if r.get(k) is None else r.get(k)) for k in self.names})

    def to_numpy(self) -> Dict[str, Any]:
        import numpy as np
        out: Dict[str, Any] = {}
        for c in self.names:
            vals = [r.get(c) for r in self._rows]
            if all(isinstance(v, (int, float)) or v is None for v in vals):
                out[c] = np.array([np.nan if v is None else float(v) for v in vals], dtype=float)
            else:
                out[c] = np.array([("" if v is None else str(v)) for v in vals], dtype=object)
        return out

    def to_arrow(self):
        import pyarrow as pa
        return pa.table({c: [r.get(c) for r in self._rows] for c in self.names})

    def to_parquet(self, path: str) -> None:
        import pyarrow.parquet as pq
        pq.write_table(self.to_arrow(), path)

    def pretty(self) -> str:
        widths = {c: max(len(c), *(len(_fmt(r.get(c))) for r in self._rows)) if self._rows
                  else len(c) for c in self.names}
        head = "  ".join(c.ljust(widths[c]) for c in self.names)
        body = "\n".join("  ".join(_fmt(r.get(c)).ljust(widths[c]) for c in self.names)
                         for r in self._rows)
        return head + ("\n" + body if body else "")


def _fmt(v: Any) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return ("%.3g" % v)
    return str(v)


# -- the projection ----------------------------------------------------------

def project(stage, paths: Optional[List[str]] = None,
            columns: Optional[List[str]] = None, xform_cache=None) -> Table:
    """Prim-level numeric table over `paths` (default: every active/defined/
    non-abstract prim, instance proxies included -- the resolve_seeds
    traversal). `columns` defaults to the cheap tier; naming an expensive
    column includes it (None where the prim isn't loaded). Never loads anything
    itself -- the caller controls load state, so a cheap-only projection stays
    surgical."""
    from pxr import Usd, UsdGeom

    cols = list(columns) if columns else list(CHEAP_METRICS)
    if "path" in cols:
        cols.remove("path")
    cols = ["path"] + cols
    unknown = [c for c in cols if c not in METRIC_NAMES and not c.startswith("attr:")]
    if unknown:
        raise ValueError("unknown metric(s): %s (known: %s; or attr:<name> for "
                         "any authored attribute/primvar)"
                         % (", ".join(unknown), ", ".join(METRIC_NAMES)))

    cache = xform_cache or UsdGeom.XformCache()

    if paths is None:
        prims = list(stage.Traverse(Usd.TraverseInstanceProxies(
            Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)))
    else:
        prims = [stage.GetPrimAtPath(p) for p in paths]
        prims = [p for p in prims if p and p.IsValid()]

    rows = [{c: _metric(c, p, cache) for c in cols} for p in prims]
    return Table(cols, rows)


def _world_bbox_from_hint(prim, cache):
    """Local extent (extentsHint, else extent) + world translation -- the cheap,
    no-load spatial read ask.spatial_candidates uses. Returns (lo, hi) in world
    translation space, or None when no extent is authored (so bbox metrics are
    None, never a load)."""
    a = prim.GetAttribute("extentsHint")
    if not (a and a.HasAuthoredValue()):
        a = prim.GetAttribute("extent")
        if not (a and a.HasAuthoredValue()):
            return None
    ext = a.Get()
    if ext is None or len(ext) < 2:
        return None
    lo, hi = ext[0], ext[1]
    t = cache.GetLocalToWorldTransform(prim).ExtractTranslation()
    return ((t[0] + lo[0], t[1] + lo[1], t[2] + lo[2]),
            (t[0] + hi[0], t[1] + hi[1], t[2] + hi[2]))


def _metric(name, prim, cache):
    from pxr import UsdGeom

    if name == "path":
        return prim.GetPath().pathString
    if name == "type":
        return str(prim.GetTypeName())
    if name == "has_payload":
        return bool(prim.HasAuthoredPayloads())

    # attr:<name> -- any authored attribute/primvar, surfaced as DATA (never a
    # relationship). Scalar value kept as-is (tokens/paths/vecs stringified);
    # an array-typed attribute reports its length (the datum that fits a cell).
    # None where unauthored or behind an unloaded payload -- lazy-consistent.
    if name.startswith("attr:"):
        a = prim.GetAttribute(name[len("attr:"):])
        if not (a and a.HasAuthoredValue()):
            return None
        v = a.Get()
        if v is None:
            return None
        if a.GetTypeName().isArray:
            try:
                return len(v)
            except TypeError:
                return None
        if isinstance(v, (int, float, bool)):
            return v
        return str(v)

    if name in ("bbox_volume", "centroid_x", "centroid_y", "centroid_z"):
        box = _world_bbox_from_hint(prim, cache)
        if box is None:
            return None
        lo, hi = box
        if name == "bbox_volume":
            # from local dims (translation-invariant); scale not applied -- a v1
            # approximation matching ask.spatial_candidates' translation-only read.
            return float(abs((hi[0] - lo[0]) * (hi[1] - lo[1]) * (hi[2] - lo[2])))
        i = {"centroid_x": 0, "centroid_y": 1, "centroid_z": 2}[name]
        return float((lo[i] + hi[i]) / 2.0)

    # expensive: aggregate over the prim's subtree, because a placement is a
    # container whose geometry lives in child gprims (ALab, and the demo bench).
    # If any prim in the subtree is an unloaded payload, the count is genuinely
    # unknown without loading -> None (never a fabricated undercount).
    if name in ("point_count", "poly_count", "byte_cost"):
        gprims, unknown = _subtree_gprims(prim)
        if unknown:
            return None          # an unloaded payload hides unknown geometry
        if not gprims:
            return None          # no mesh/point geometry here (e.g. implicit
                                 # Cube/Cylinder, or a pure container) -> N/A,
                                 # never a misleading 0
        pts = polys = 0
        for g in gprims:
            p = UsdGeom.PointBased(g).GetPointsAttr().Get()
            pts += 0 if p is None else len(p)
            fvc = UsdGeom.Mesh(g).GetFaceVertexCountsAttr().Get()
            polys += 0 if fvc is None else len(fvc)
        if name == "point_count":
            return pts
        if name == "poly_count":
            return polys
        return int(pts * 12 + polys * 4)      # byte_cost (rough)

    raise ValueError("unknown metric %r" % name)


def _subtree_gprims(prim):
    """(gprims, unknown): the PointBased prims in `prim`'s subtree (self +
    descendants), and whether an unloaded payload sits anywhere in it. Uses the
    load-agnostic predicate (active/defined/non-abstract) so an unloaded
    placement is still visited and flagged, rather than silently skipped."""
    from pxr import Usd, UsdGeom
    pred = Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract
    gprims, unknown = [], False
    for p in Usd.PrimRange(prim, pred):
        if p.HasAuthoredPayloads() and not p.IsLoaded():
            unknown = True
        if UsdGeom.PointBased(p):
            gprims.append(p)
    return gprims, unknown
