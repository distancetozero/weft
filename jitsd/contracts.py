"""Type-directed contract resolution.

The first thing here that USD cannot do. Consumers declare a *requirement*
against a contract identity; providers declare an *offer* satisfying one; the
resolver matches them by type. No prim paths cross an asset boundary in either
direction, so renaming a provider's internals cannot break a consumer.

Two operations:

  resolve()               bind requirements to offers by contract identity.
  check_compatibility()   compare a candidate revision's offers against the
                          ones currently in force. This is the promotion gate:
                          compatibility is measured, not asserted.

The envelope is what makes the gate meaningful. An offer declares how far it
may move without consumers caring. Moving inside it is compatible and silent;
moving outside it is the provider breaking its own promise, and the promotion
is refused and names the offer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Sequence, Tuple

from .usda import Layer, Prim, parse

OFFER_API = "JitsdOfferAPI"
REQUIRE_API = "JitsdRequireAPI"
ENVELOPE_API = "JitsdEnvelopeAPI"


def split_contract(ident: str) -> Tuple[str, int]:
    """'Mount@2' -> ('Mount', 2). An unversioned contract is major 0."""
    if "@" in ident:
        name, _, major = ident.partition("@")
        try:
            return name, int(major)
        except ValueError:
            return name, 0
    return ident, 0


# -- binding attributes ---------------------------------------------------
#
# A relationship is not a position. It is a set of named attributes, and each
# kind carries its own rule for what "still compatible" means. A view -- a
# department, a context -- is which attributes a consumer reads. Lighting
# binds on material and position; FX on collision purpose and position; an
# engineer on power and never on material. Same parts, same contracts.
#
#   spatial   a point; compatible while it moved less than a tolerance
#   angular   an orientation; compatible while it turned less than a tolerance
#   exact     a token; compatible while unchanged
#   set       tokens; compatible while everything required is still offered
#
# Threshold and aggregate kinds (power draw, busway capacity) are deliberately
# absent: they need a solver, not a comparison, and are a separate piece.

SPATIAL, ANGULAR, EXACT, SET = "spatial", "angular", "exact", "set"
KINDS = (SPATIAL, ANGULAR, EXACT, SET)

# Every offer has these two, synthesised from its frame and envelope, so all
# comparison goes through one path.
POSITION, ORIENTATION = "position", "orientation"


@dataclass
class Attribute:
    kind: str
    value: object
    tolerance: Optional[float] = None   # spatial/angular only; None = unstated

    def to_dict(self) -> Dict:
        return {"kind": self.kind, "value": self.value, "tolerance": self.tolerance}

    @classmethod
    def from_dict(cls, d: Dict) -> "Attribute":
        v = d.get("value")
        if isinstance(v, list) and d.get("kind") in (SPATIAL, ANGULAR):
            v = tuple(v)
        return cls(kind=d["kind"], value=v, tolerance=d.get("tolerance"))


def _infer_kind(value) -> Optional[str]:
    if isinstance(value, (list, tuple)):
        if len(value) == 3 and all(isinstance(x, (int, float)) for x in value):
            return SPATIAL
        if all(isinstance(x, str) for x in value):
            return SET
        return None
    if isinstance(value, str):
        return EXACT
    return None


def _read_binds(prim: Prim, prefix: str) -> Dict[str, Attribute]:
    """`<prefix><name>`, with optional `<prefix><name>:kind` and `:tolerance`."""
    out: Dict[str, Attribute] = {}
    for k, v in prim.attrs.items():
        if not k.startswith(prefix):
            continue
        rest = k[len(prefix):]
        if ":" in rest or v is None:
            continue
        kind = prim.attrs.get("%s%s:kind" % (prefix, rest)) or _infer_kind(v)
        if kind not in KINDS:
            continue
        tol = prim.attrs.get("%s%s:tolerance" % (prefix, rest))
        val = tuple(float(x) for x in v) if kind in (SPATIAL, ANGULAR) else \
              (sorted(str(x) for x in v) if kind == SET else str(v))
        out[rest] = Attribute(kind, val, float(tol) if tol is not None else None)
    return out


def _binds_to_dict(b: Dict[str, Attribute]) -> Dict:
    return {k: a.to_dict() for k, a in b.items()}


def _binds_from_dict(d: Optional[Dict]) -> Dict[str, Attribute]:
    return {k: Attribute.from_dict(a) for k, a in (d or {}).items()}


@dataclass
class Offer:
    path: str
    contract: str
    archetype: str = ""
    role: str = ""
    public: bool = True
    frame: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    orient: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    envelope_linear: float = 0.0
    envelope_angular: float = 0.0
    binds: Dict[str, Attribute] = field(default_factory=dict)

    @property
    def key(self) -> Tuple[str, int]:
        return split_contract(self.contract)

    def attributes(self) -> Dict[str, Attribute]:
        """Everything this offer binds on, position and orientation included."""
        out = {
            POSITION: Attribute(SPATIAL, tuple(self.frame), self.envelope_linear),
            ORIENTATION: Attribute(ANGULAR, tuple(self.orient), self.envelope_angular),
        }
        out.update(self.binds)
        return out


@dataclass
class Requirement:
    path: str
    instance: str
    contract: str
    role: str = ""
    cardinality: str = "one"          # one | many
    failure_policy: str = "required"  # required | substitutable | omittable
    # What this consumer constrains and how much it tolerates. An exact/set
    # attribute here must be satisfied by a candidate offer to bind at all.
    # A spatial/angular tolerance here is the consumer's OWN limit, checked at
    # re-evaluation -- the provider's envelope is what it asserts; this is what
    # gets measured.
    binds: Dict[str, Attribute] = field(default_factory=dict)

    @property
    def key(self) -> Tuple[str, int]:
        return split_contract(self.contract)

    def tolerance(self, name: str) -> Optional[float]:
        a = self.binds.get(name)
        return a.tolerance if a else None

    def satisfied_by(self, offer: Offer, view: Optional[Sequence[str]] = None) -> bool:
        """Exact and set constraints, the ones that decide binding."""
        have = offer.attributes()
        for name, want in self.binds.items():
            if view is not None and name not in view:
                continue
            if want.kind not in (EXACT, SET):
                continue
            got = have.get(name)
            if got is None:
                return False
            if want.kind == EXACT and got.value != want.value:
                return False
            if want.kind == SET and not set(want.value).issubset(set(got.value)):
                return False
        return True


@dataclass
class Surface:
    """An asset's contract surface: what it offers and what it needs."""
    offers: List[Offer] = field(default_factory=list)
    requires: List[Requirement] = field(default_factory=list)

    def to_dict(self) -> Dict:
        def offer(o: Offer) -> Dict:
            d = asdict(o)
            d["binds"] = _binds_to_dict(o.binds)
            return d

        def req(r: Requirement) -> Dict:
            d = asdict(r)
            d["binds"] = _binds_to_dict(r.binds)
            return d

        return {"offers": [offer(o) for o in self.offers],
                "requires": [req(r) for r in self.requires]}

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "Surface":
        if not d:
            return cls()
        offers = []
        for o in d.get("offers", []):
            o = dict(o)
            o["frame"] = tuple(o.get("frame", (0.0, 0.0, 0.0)))
            o["orient"] = tuple(o.get("orient", (0.0, 0.0, 0.0)))
            o["binds"] = _binds_from_dict(o.get("binds"))
            offers.append(Offer(**o))
        requires = []
        for r in d.get("requires", []):
            r = dict(r)
            r["binds"] = _binds_from_dict(r.get("binds"))
            requires.append(Requirement(**r))
        return cls(offers=offers, requires=requires)

    def __bool__(self) -> bool:
        return bool(self.offers or self.requires)


def _frame_of(prim: Prim) -> Tuple[float, float, float]:
    t = prim.attrs.get("xformOp:translate")
    if isinstance(t, (tuple, list)) and len(t) == 3:
        return tuple(float(x) for x in t)
    m = prim.attrs.get("xformOp:transform")
    if isinstance(m, (tuple, list)) and len(m) == 4:
        row = m[3]
        if isinstance(row, (tuple, list)) and len(row) >= 3:
            return tuple(float(x) for x in row[:3])
    return (0.0, 0.0, 0.0)


def _orient_of(prim: Prim) -> Tuple[float, float, float]:
    """The offer's orientation, as XYZ degrees.

    A mount is a frame, not a point. Reading only the translation means a hub
    can rotate 180 degrees and promote clean, which is exactly the breakage the
    envelope exists to catch.
    """
    r = prim.attrs.get("xformOp:rotateXYZ")
    if isinstance(r, (tuple, list)) and len(r) == 3:
        return tuple(float(x) for x in r)
    m = prim.attrs.get("xformOp:transform")
    if isinstance(m, (tuple, list)) and len(m) == 4:
        return _euler_from_matrix(m)
    return (0.0, 0.0, 0.0)


def _euler_from_matrix(m) -> Tuple[float, float, float]:
    """XYZ Euler degrees from the upper-left 3x3 of a row-major USD matrix."""
    try:
        r0, r1, r2 = (list(m[0])[:3], list(m[1])[:3], list(m[2])[:3])
    except (TypeError, IndexError):
        return (0.0, 0.0, 0.0)
    # USD matrices are row-major with basis vectors in rows.
    sy = math.sqrt(r0[0] * r0[0] + r0[1] * r0[1])
    if sy > 1e-9:
        x = math.atan2(r1[2], r2[2])
        y = math.atan2(-r0[2], sy)
        z = math.atan2(r0[1], r0[0])
    else:
        x = math.atan2(-r2[1], r1[1])
        y = math.atan2(-r0[2], sy)
        z = 0.0
    return tuple(math.degrees(v) for v in (x, y, z))


def _angular_delta(a: Tuple[float, float, float],
                   b: Tuple[float, float, float]) -> float:
    """Largest per-axis rotation difference in degrees, wrapped to +/-180."""
    worst = 0.0
    for u, v in zip(a, b):
        d = abs((u - v + 180.0) % 360.0 - 180.0)
        worst = max(worst, d)
    return worst


def extract(layer: Layer) -> Surface:
    """Read a contract surface out of a parsed layer."""
    surface = Surface()
    for prim in layer.walk():
        if prim.has_api(OFFER_API):
            contract = prim.attrs.get("jitsd:offer:contract")
            if contract:
                surface.offers.append(
                    Offer(
                        path=prim.path,
                        contract=str(contract),
                        archetype=str(prim.attrs.get("jitsd:offer:archetype") or ""),
                        role=str(prim.attrs.get("jitsd:mount:role") or ""),
                        public=bool(prim.attrs.get("jitsd:offer:public", True)),
                        frame=_frame_of(prim),
                        orient=_orient_of(prim),
                        envelope_linear=float(prim.attrs.get("jitsd:envelope:linear") or 0.0),
                        envelope_angular=float(prim.attrs.get("jitsd:envelope:angular") or 0.0),
                        binds=_read_binds(prim, "jitsd:bind:"),
                    )
                )
        for inst in prim.api_instances(REQUIRE_API):
            pre = "jitsd:require:%s:" % inst
            contract = prim.attrs.get(pre + "contract")
            if contract:
                binds = _read_binds(prim, pre + "bind:")
                # The consumer's own spatial/angular tolerances, if declared.
                tl = prim.attrs.get(pre + "tolerance:linear")
                ta = prim.attrs.get(pre + "tolerance:angular")
                if tl is not None:
                    binds[POSITION] = Attribute(SPATIAL, None, float(tl))
                if ta is not None:
                    binds[ORIENTATION] = Attribute(ANGULAR, None, float(ta))
                surface.requires.append(
                    Requirement(
                        path=prim.path,
                        instance=inst,
                        contract=str(contract),
                        role=str(prim.attrs.get(pre + "role") or ""),
                        cardinality=str(prim.attrs.get(pre + "cardinality") or "one"),
                        failure_policy=str(prim.attrs.get(pre + "failurePolicy") or "required"),
                        binds=binds,
                    )
                )
    return surface


def extract_text(text: str) -> Surface:
    return extract(parse(text))


# -- resolution -----------------------------------------------------------

@dataclass
class Binding:
    consumer: str        # asset name
    requirement: str     # "path:instance"
    contract: str
    providers: List[str] = field(default_factory=list)  # "asset:offerPath"


@dataclass
class Diagnostic:
    severity: str        # error | warning | info
    consumer: str
    requirement: str
    message: str

    def __str__(self) -> str:
        return "%-7s %s %s: %s" % (self.severity, self.consumer, self.requirement, self.message)


@dataclass
class Resolution:
    bindings: List[Binding] = field(default_factory=list)
    diagnostics: List[Diagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not any(d.severity == "error" for d in self.diagnostics)


def resolve(surfaces: Dict[str, Surface],
            view: Optional[Sequence[str]] = None) -> Resolution:
    """Bind every requirement to offers, by contract identity and attributes.

    `view` restricts which binding attributes participate -- a context reading
    only the attributes it cares about. None means all of them.
    """
    res = Resolution()

    # Indexed by contract key so each requirement is a lookup, not a scan of
    # the whole catalogue -- the difference between closure being linear and
    # quadratic in the number of assets (bench/closure.py).
    by_key: Dict[Tuple[str, int], List[Tuple[str, Offer]]] = {}
    by_name: Dict[str, List[Tuple[str, Offer]]] = {}
    for asset, s in sorted(surfaces.items()):
        for o in s.offers:
            if o.public:
                by_key.setdefault(o.key, []).append((asset, o))
                by_name.setdefault(o.key[0], []).append((asset, o))

    for consumer, surface in sorted(surfaces.items()):
        for req in surface.requires:
            ref = "%s:%s" % (req.path, req.instance)
            name, major = req.key
            candidates = [
                (a, o) for a, o in by_key.get((name, major), [])
                if a != consumer and (not req.role or o.role == req.role)
                and req.satisfied_by(o, view)
            ]

            if not candidates:
                # Failure policy is declared, not exceptional.
                loose = [(a, o) for a, o in by_name.get(name, [])
                         if a != consumer and o.key[1] != major]
                if loose:
                    have = ", ".join(sorted({o.contract for _, o in loose}))
                    msg = "no provider of %s (found incompatible major: %s)" % (req.contract, have)
                else:
                    msg = "no provider of %s" % req.contract
                if req.failure_policy == "required":
                    res.diagnostics.append(Diagnostic("error", consumer, ref, msg))
                elif req.failure_policy == "substitutable":
                    res.diagnostics.append(Diagnostic("warning", consumer, ref, msg + "; substituting"))
                else:
                    res.diagnostics.append(Diagnostic("info", consumer, ref, msg + "; omitted"))
                continue

            if req.cardinality == "one" and len(candidates) > 1:
                where = ", ".join("%s%s" % (a, o.path) for a, o in candidates)
                res.diagnostics.append(Diagnostic(
                    "error", consumer, ref,
                    "ambiguous: %d providers of %s (%s) -- "
                    "declare cardinality 'many' or narrow by role"
                    % (len(candidates), req.contract, where)))
                continue

            chosen = candidates if req.cardinality == "many" else candidates[:1]
            res.bindings.append(Binding(
                consumer=consumer,
                requirement=ref,
                contract=req.contract,
                providers=["%s%s" % (a, o.path) for a, o in chosen],
            ))

    return res


# -- the promotion gate ---------------------------------------------------

@dataclass
class Violation:
    kind: str        # removed | major-bump | envelope | envelope-tightened
    offer: str
    detail: str
    breaking: bool = True

    def __str__(self) -> str:
        return "%-18s %s: %s" % (self.kind, self.offer, self.detail)


def check_compatibility(old: Surface, new: Surface) -> List[Violation]:
    """Compare a candidate revision's offers against the ones in force.

    Compatible: offers added; an offer moving within its declared envelope.
    Breaking:   an offer removed, its contract major bumped, its envelope
                tightened, or its frame moved beyond the envelope it promised.
    """
    out: List[Violation] = []
    new_by_path = {o.path: o for o in new.offers}

    for o in old.offers:
        n = new_by_path.get(o.path)
        if n is None:
            out.append(Violation("removed", o.path,
                                 "offer %s no longer provided" % o.contract))
            continue

        # Withdrawing an offer from the public catalogue, or re-roling it, is
        # observationally identical to deleting it: resolve() filters on
        # `public` and narrows on `role`, so either change silently removes a
        # provider while the gate reports "compatible".
        if o.public and not n.public:
            out.append(Violation(
                "unpublished", o.path,
                "offer %s is no longer public; consumers can no longer bind it"
                % o.contract))
            continue

        if o.role != n.role:
            out.append(Violation(
                "role-changed", o.path,
                "role %r -> %r; requirements narrowed by role stop matching"
                % (o.role or "(none)", n.role or "(none)")))
            continue

        oname, omaj = o.key
        nname, nmaj = n.key
        if (oname, omaj) != (nname, nmaj):
            out.append(Violation("major-bump", o.path,
                                 "%s -> %s" % (o.contract, n.contract)))
            continue

        if n.envelope_linear < o.envelope_linear:
            out.append(Violation(
                "envelope-tightened", o.path,
                "linear envelope %.4g -> %.4g; consumers relying on the old "
                "room lose it" % (o.envelope_linear, n.envelope_linear)))

        if n.envelope_angular < o.envelope_angular:
            out.append(Violation(
                "envelope-tightened", o.path,
                "angular envelope %.4g -> %.4g deg; consumers relying on the old "
                "room lose it" % (o.envelope_angular, n.envelope_angular)))

        moved = math.dist(o.frame, n.frame)
        if moved > o.envelope_linear:
            out.append(Violation(
                "envelope", o.path,
                "moved %.4g, envelope allows %.4g -- provider broke its own "
                "promise" % (moved, o.envelope_linear)))

        turned = _angular_delta(o.orient, n.orient)
        if turned > o.envelope_angular:
            out.append(Violation(
                "envelope-angular", o.path,
                "rotated %.4g deg, envelope allows %.4g -- provider broke its "
                "own promise" % (turned, o.envelope_angular)))

        # Declared attributes are facts consumers bind on. Changing or dropping
        # one is observationally a re-role for anyone constrained on it.
        for aname, old_a in o.binds.items():
            new_a = n.binds.get(aname)
            if new_a is None:
                out.append(Violation("attribute-removed", o.path,
                                     "%s no longer declared" % aname))
            elif old_a.kind == EXACT and new_a.value != old_a.value:
                out.append(Violation("attribute-changed", o.path,
                                     "%s %r -> %r" % (aname, old_a.value, new_a.value)))
            elif old_a.kind == SET and not set(old_a.value).issubset(set(new_a.value)):
                lost = sorted(set(old_a.value) - set(new_a.value))
                out.append(Violation("attribute-narrowed", o.path,
                                     "%s no longer offers %s" % (aname, ", ".join(lost))))
    return out


def summarise(violations: Sequence[Violation]) -> str:
    if not violations:
        return "compatible"
    return "breaking: %d violation%s" % (len(violations), "" if len(violations) == 1 else "s")
