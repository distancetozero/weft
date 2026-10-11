"""The ask: seed predicates that resolve to composed prim paths
(spec section 5). Parsing here is pure Python; resolution against a stage
lives below it and needs pxr. v1 operator set: `=` only — `~`, `<`, `>`
and conjunction are reserved, and reserved syntax fails loudly."""

from __future__ import annotations

from dataclasses import dataclass

_RESERVED_OPS = ("~", "<", ">", "!", "&")


@dataclass(frozen=True)
class Seed:
    plane: str
    key: str
    value: str
    raw: str


def parse_seed(text: str) -> Seed:
    t = text.strip()
    if t.startswith("id:occ:"):
        return Seed("identity", "occ", t[len("id:occ:"):], t)
    if t.startswith("id:"):
        return Seed("identity", "", t[len("id:"):], t)
    for key in ("role", "offers", "requires"):
        p = key + ":"
        if t.startswith(p):
            return Seed("contract", key, t[len(p):], t)
    if t.startswith("where:"):
        body = t[len("where:"):]
        for op in ("~", "&"):           # combinators still reserved in v1
            if op in body:
                raise ValueError("where: operator %r is reserved" % op)
        # numeric metric predicate: <metric><op><number>. Check the two-char
        # operators before the one-char ones, and before the facet '='.
        from .data import METRIC_NAMES, SELECTABLE_METRICS
        for op in (">=", "<=", "==", "!=", ">", "<"):
            if op in body:
                key, _, num = body.partition(op)
                key, num = key.strip(), num.strip()
                if key not in METRIC_NAMES:
                    raise ValueError(
                        "where: comparison needs a numeric metric; %r is not one "
                        "(try one of %s)" % (key, ", ".join(sorted(SELECTABLE_METRICS))))
                if key not in SELECTABLE_METRICS:
                    raise ValueError(
                        "where: %r is not selectable (expensive or non-numeric); "
                        "tabulate it with `weft data --load --columns %s`" % (key, key))
                try:
                    float(num)
                except ValueError:
                    raise ValueError("where: %r wants a number, got %r" % (key, num))
                return Seed("metric", key, op + num, t)
        if "=" not in body:
            raise ValueError("where: wants attr=value or metric<op>number, got %r" % body)
        key, _, value = body.partition("=")
        if not key or not value:
            raise ValueError("where: wants attr=value, got %r" % body)
        return Seed("attr", key, value, t)
    if t.startswith("within:"):
        vals = t[len("within:"):].split(",")
        if len(vals) != 6:
            raise ValueError("within: wants x0,y0,z0,x1,y1,z1 (6 numbers)")
        for v in vals:
            try:
                float(v)
            except ValueError:
                raise ValueError("within: wants x0,y0,z0,x1,y1,z1 (6 numbers)")
        return Seed("spatial", "within", ",".join(vals), t)
    if t.startswith("near:"):
        body = t[len("near:"):]
        if "," not in body:
            raise ValueError("near: wants SEED,RADIUS")
        inner, _, radius = body.rpartition(",")
        try:
            float(radius)
        except ValueError:
            raise ValueError("near: wants SEED,RADIUS with a numeric radius")
        return Seed("spatial", "near", body, t)
    if t.startswith("material:"):
        return Seed("material", "", t[len("material:"):], t)
    if t.startswith("type:"):
        return Seed("type", "", t[len("type:"):], t)
    if t.startswith("path:"):
        return Seed("path", "", t[len("path:"):], t)
    if t.startswith("name:"):
        return Seed("name", "", t[len("name:"):], t)
    return Seed("name", "", t, t)


import fnmatch
from typing import Dict, List, Optional, Tuple

DEFAULT_IDENTITY_KEYS = ("absent:id", "weft:id", "ifc:GlobalId")


from dataclasses import dataclass as _dc, field as _field


@_dc
class ResolvedSeed:
    seed: Seed
    paths: List[str] = _field(default_factory=list)
    mode: str = ""
    matched: int = 0
    complement: int = 0
    note: str = ""


def identity_of(prim, keys=DEFAULT_IDENTITY_KEYS) -> Optional[str]:
    cd = prim.GetCustomData()
    for k in keys:
        if k in cd:
            return str(cd[k])
    v = prim.GetAssetInfoByKey("identifier")
    return str(v) if v else None


def _value_matches(authored, text: str) -> bool:
    """Canonical-typed equality: parse text to the authored value's type."""
    if isinstance(authored, bool):
        return text.lower() in ("true", "1") if authored else text.lower() in ("false", "0")
    if isinstance(authored, (int, float)):
        try:
            return float(text) == float(authored)
        except ValueError:
            return False
    return str(authored) == text


def _authored(prim, name):
    """Authored value for `name`: attribute (plain or weft:bind:), then
    customData. Returns (found, value)."""
    for attr_name in (name, "weft:bind:%s" % name):
        a = prim.GetAttribute(attr_name)
        if a and a.HasAuthoredValue():
            return True, a.Get()
    cd = prim.GetCustomData()
    if name in cd:
        return True, cd[name]
    return False, None


def _world_pos(prim, cache):
    m = cache.GetLocalToWorldTransform(prim)
    t = m.ExtractTranslation()
    return (t[0], t[1], t[2])


def resolve_seeds(stage, seed_texts, identity_keys=DEFAULT_IDENTITY_KEYS):
    from pxr import Usd, UsdGeom

    seeds = [parse_seed(t) for t in seed_texts]
    # The context stage is opened with LoadNone (pull.py._open) -- pulling a
    # thread must never require loading first. Usd's default predicate
    # requires UsdPrimIsLoaded, which on a LoadNone stage silently drops
    # every prim that sits behind an unloaded payload arc (in production
    # data, that is most placements) from seed matching entirely. Drop the
    # loaded requirement; keep active/defined/non-abstract. Also traverse
    # instance proxies: an instanceable placement's own contract surface
    # (e.g. a `represents` offer authoring `weft:bind:finish`) lives inside
    # the prototype and is otherwise invisible to attribute/name matching.
    # `pull()`'s `_admit` already widens a resolved instance-proxy path back
    # to its instance root, so surfacing the proxy path here is safe.
    # The full-stage traversal and the identity index are built LAZILY: a
    # path: seed needs neither, so a targeted pull no longer walks every prim.
    # (Profiling a 1-member ALab pull, this identity index over 4,541 prims was
    # ~14% of resolve_seeds' time, read by nothing.)
    cache = UsdGeom.XformCache()
    out: List[ResolvedSeed] = []
    planes = {s.plane for s in seeds}

    _prims: Optional[List] = None

    def prims_list():
        nonlocal _prims
        if _prims is None:
            _prims = [p for p in stage.Traverse(Usd.TraverseInstanceProxies(
                Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract))]
        return _prims

    ids: Dict[str, List[str]] = {}
    if "identity" in planes:
        for p in prims_list():
            i = identity_of(p, identity_keys)
            if i:
                ids.setdefault(i, []).append(p.GetPath().pathString)

    def spatial_candidates():
        for p in prims_list():
            a = p.GetAttribute("extentsHint")
            if a and a.HasAuthoredValue():
                lo, hi = a.Get()[0], a.Get()[1]
                cx, cy, cz = _world_pos(p, cache)
                yield p, (cx + lo[0], cy + lo[1], cz + lo[2]), (cx + hi[0], cy + hi[1], cz + hi[2])

    for s in seeds:
        r = ResolvedSeed(seed=s)
        if s.plane == "name":
            r.mode = "lexical"
            r.paths = sorted(p.GetPath().pathString for p in prims_list()
                             if fnmatch.fnmatchcase(p.GetName(), s.value))
        elif s.plane == "identity":
            r.mode = "identity"
            r.paths = sorted(ids.get(s.value, []))
            if len(r.paths) > 1:
                if s.key == "occ":
                    r.note = "occurrence id matches %d prims — ambiguous: %s" % (len(r.paths), ", ".join(r.paths))
                else:
                    r.note = "type identity: %d placements" % len(r.paths)
        elif s.plane == "material":
            # prims bound to a material matching the value, by full OR preview
            # purpose. Value is an exact material path (/root/mtl/glass) or an
            # fnmatch on the material's leaf name (glass, glass*). Expensive:
            # bindings sit behind payloads, so an unloaded stage matches little.
            r.mode = "material"
            from pxr import UsdShade
            val = s.value

            def _mat_hit(prim):
                api = UsdShade.MaterialBindingAPI(prim)
                for purpose in (UsdShade.Tokens.full, UsdShade.Tokens.preview):
                    try:
                        mat, _rel = api.ComputeBoundMaterial(purpose)
                    except Exception:
                        continue
                    if not (mat and mat.GetPrim() and mat.GetPrim().IsValid()):
                        continue
                    mp = mat.GetPath().pathString
                    if (mp == val) if val.startswith("/") \
                            else fnmatch.fnmatchcase(mp.rsplit("/", 1)[-1], val):
                        return True
                return False

            r.paths = sorted(p.GetPath().pathString for p in prims_list()
                             if _mat_hit(p))
            if not r.paths:
                r.note = ("no prim bound to a material matching %r "
                          "(bindings may be behind unloaded payloads -- load first)" % val)
        elif s.plane == "type":
            # prims whose schema type name fnmatches the value (Mesh, *Light)
            r.mode = "type"
            r.paths = sorted(p.GetPath().pathString for p in prims_list()
                             if fnmatch.fnmatchcase(p.GetTypeName(), s.value))
            if not r.paths:
                r.note = "no prim of type %r in the composed world" % s.value
        elif s.plane == "path":
            r.mode = "path"
            if any(c in s.value for c in "*?["):
                # a path glob: match full prim paths (e.g. /root/set/lab_* for a
                # whole family of subtrees). Exact paths stay targeted (no walk).
                r.paths = sorted(p.GetPath().pathString for p in prims_list()
                                 if fnmatch.fnmatchcase(p.GetPath().pathString, s.value))
                if not r.paths:
                    r.note = "path glob %s matched nothing in the composed world" % s.value
            else:
                prim = stage.GetPrimAtPath(s.value)
                r.paths = [s.value]  # Always include the path
                if not prim:
                    r.note = "path %s not in composed world (may lie below an unloaded payload)" % s.value
        elif s.plane == "attr":
            r.mode = "attribute"
            hits, absent = [], 0
            for p in prims_list():
                found, v = _authored(p, s.key)
                if not found:
                    absent += 1
                    continue
                values = v if isinstance(v, (list, tuple)) else [v]
                if any(_value_matches(x, s.value) for x in values):
                    hits.append(p.GetPath().pathString)
            r.paths, r.complement = sorted(hits), absent
        elif s.plane == "spatial":
            r.mode = "spatial"
            hits, without = [], 0
            for p in prims_list():
                a = p.GetAttribute("extentsHint")
                if not (a and a.HasAuthoredValue()):
                    without += 1
            if s.key == "within":
                v = [float(x) for x in s.value.split(",")]
                box = ((v[0], v[1], v[2]), (v[3], v[4], v[5]))
                for p, lo, hi in spatial_candidates():
                    if all(lo[i] <= box[1][i] and box[0][i] <= hi[i] for i in range(3)):
                        hits.append(p.GetPath().pathString)
            else:  # near:SEED,RADIUS
                inner, _, radius = s.value.rpartition(",")
                rad = float(radius)
                anchor = resolve_seeds(stage, [inner], identity_keys)[0]
                centers = []
                for ap in anchor.paths:
                    prim = stage.GetPrimAtPath(ap)
                    if prim:
                        centers.append(_world_pos(prim, cache))
                for p, lo, hi in spatial_candidates():
                    c = tuple((lo[i] + hi[i]) / 2.0 for i in range(3))
                    if any(sum((c[i] - a[i]) ** 2 for i in range(3)) <= rad * rad
                           for a in centers):
                        hits.append(p.GetPath().pathString)
            r.paths, r.complement = sorted(set(hits)), without
        elif s.plane == "contract":
            r.mode = "contract"
            hits = []
            for p in prims_list():
                found, v = _authored(p, "weft:offer:contract")
                rfound, rv = _authored(p, "weft:offer:role")
                if s.key == "offers" and found and str(v).split("@")[0] == s.value.split("@")[0]:
                    hits.append(p.GetPath().pathString)
                elif s.key == "role" and rfound and str(rv) == s.value:
                    hits.append(p.GetPath().pathString)
                elif s.key == "requires":
                    for prop in p.GetAuthoredPropertyNames():
                        if prop.startswith("weft:require:") and prop.endswith(":contract"):
                            a = p.GetAttribute(prop)
                            if a and str(a.Get()).split("@")[0] == s.value.split("@")[0]:
                                hits.append(p.GetPath().pathString)
                                break
            r.paths = sorted(set(hits))
        elif s.plane == "metric":
            r.mode = "metric"
            import re as _re
            from . import data as _data
            m = _re.match(r"^(>=|<=|==|!=|>|<)(.+)$", s.value)
            op, num = m.group(1), float(m.group(2))
            # cheap, no-load projection of just this metric over the candidates
            cand = [p.GetPath().pathString for p in prims_list()]
            tbl = _data.project(stage, cand, columns=[s.key], xform_cache=cache)
            hits, without = [], 0
            for row in tbl.rows():
                v = row.get(s.key)
                if v is None:
                    without += 1
                    continue
                if _data.compare(v, op, num):
                    hits.append(row["path"])
            r.paths, r.complement = sorted(hits), without
        r.matched = len(r.paths)
        if not r.paths and not r.note:
            r.note = "seed %r matched nothing" % s.raw
        out.append(r)
    return out
