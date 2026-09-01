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
        for op in _RESERVED_OPS:
            if op in body:
                raise ValueError("where: operator %r is reserved; v1 has '=' only" % op)
        if "=" not in body:
            raise ValueError("where: wants attr=value, got %r" % body)
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
    if t.startswith("path:"):
        return Seed("path", "", t[len("path:"):], t)
    if t.startswith("name:"):
        return Seed("name", "", t[len("name:"):], t)
    return Seed("name", "", t, t)


import fnmatch
from typing import Dict, List, Optional, Tuple

DEFAULT_IDENTITY_KEYS = ("absent:id", "jitsd:id", "ifc:GlobalId")


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
    """Authored value for `name`: attribute (plain or jitsd:bind:), then
    customData. Returns (found, value)."""
    for attr_name in (name, "jitsd:bind:%s" % name):
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
    from pxr import UsdGeom

    seeds = [parse_seed(t) for t in seed_texts]
    prims = [p for p in stage.Traverse()]
    cache = UsdGeom.XformCache()
    out: List[ResolvedSeed] = []

    ids: Dict[str, List[str]] = {}
    for p in prims:
        i = identity_of(p, identity_keys)
        if i:
            ids.setdefault(i, []).append(p.GetPath().pathString)

    def spatial_candidates():
        for p in prims:
            a = p.GetAttribute("extentsHint")
            if a and a.HasAuthoredValue():
                lo, hi = a.Get()[0], a.Get()[1]
                cx, cy, cz = _world_pos(p, cache)
                yield p, (cx + lo[0], cy + lo[1], cz + lo[2]), (cx + hi[0], cy + hi[1], cz + hi[2])

    for s in seeds:
        r = ResolvedSeed(seed=s)
        if s.plane == "name":
            r.mode = "lexical"
            r.paths = sorted(p.GetPath().pathString for p in prims
                             if fnmatch.fnmatchcase(p.GetName(), s.value))
        elif s.plane == "identity":
            r.mode = "identity"
            r.paths = sorted(ids.get(s.value, []))
            if len(r.paths) > 1:
                if s.key == "occ":
                    r.note = "occurrence id matches %d prims — ambiguous: %s" % (len(r.paths), ", ".join(r.paths))
                else:
                    r.note = "type identity: %d placements" % len(r.paths)
        elif s.plane == "path":
            r.mode = "path"
            prim = stage.GetPrimAtPath(s.value)
            r.paths = [s.value]  # Always include the path
            if not prim:
                r.note = "path %s not in composed world (may lie below an unloaded payload)" % s.value
        elif s.plane == "attr":
            r.mode = "attribute"
            hits, absent = [], 0
            for p in prims:
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
            for p in prims:
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
            for p in prims:
                found, v = _authored(p, "jitsd:offer:contract")
                rfound, rv = _authored(p, "jitsd:offer:role")
                if s.key == "offers" and found and str(v).split("@")[0] == s.value.split("@")[0]:
                    hits.append(p.GetPath().pathString)
                elif s.key == "role" and rfound and str(rv) == s.value:
                    hits.append(p.GetPath().pathString)
                elif s.key == "requires":
                    for prop in p.GetAuthoredPropertyNames():
                        if prop.startswith("jitsd:require:") and prop.endswith(":contract"):
                            a = p.GetAttribute(prop)
                            if a and str(a.Get()).split("@")[0] == s.value.split("@")[0]:
                                hits.append(p.GetPath().pathString)
                                break
            r.paths = sorted(set(hits))
        r.matched = len(r.paths)
        if not r.paths and not r.note:
            r.note = "seed %r matched nothing" % s.raw
        out.append(r)
    return out
