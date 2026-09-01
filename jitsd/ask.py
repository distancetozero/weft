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
        [float(v) for v in vals]  # raises ValueError on non-numbers
        return Seed("spatial", "within", ",".join(vals), t)
    if t.startswith("near:"):
        body = t[len("near:"):]
        if "," not in body:
            raise ValueError("near: wants SEED,RADIUS")
        inner, _, radius = body.rpartition(",")
        float(radius)
        return Seed("spatial", "near", body, t)
    if t.startswith("path:"):
        return Seed("path", "", t[len("path:"):], t)
    if t.startswith("name:"):
        return Seed("name", "", t[len("name:"):], t)
    return Seed("name", "", t, t)
