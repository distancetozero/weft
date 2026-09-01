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

    @property
    def key(self) -> Tuple[str, int]:
        return split_contract(self.contract)


@dataclass
class Requirement:
    path: str
    instance: str
    contract: str
    role: str = ""
    cardinality: str = "one"          # one | many
    failure_policy: str = "required"  # required | substitutable | omittable

    @property
    def key(self) -> Tuple[str, int]:
        return split_contract(self.contract)


@dataclass
class Surface:
    """An asset's contract surface: what it offers and what it needs."""
    offers: List[Offer] = field(default_factory=list)
    requires: List[Requirement] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return {
            "offers": [asdict(o) for o in self.offers],
            "requires": [asdict(r) for r in self.requires],
        }

    @classmethod
    def from_dict(cls, d: Optional[Dict]) -> "Surface":
        if not d:
            return cls()
        offers = []
        for o in d.get("offers", []):
            o = dict(o)
            o["frame"] = tuple(o.get("frame", (0.0, 0.0, 0.0)))
            o["orient"] = tuple(o.get("orient", (0.0, 0.0, 0.0)))
            offers.append(Offer(**o))
        return cls(
            offers=offers,
            requires=[Requirement(**r) for r in d.get("requires", [])],
        )

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
                    )
                )
        for inst in prim.api_instances(REQUIRE_API):
            pre = "jitsd:require:%s:" % inst
            contract = prim.attrs.get(pre + "contract")
            if contract:
                surface.requires.append(
                    Requirement(
                        path=prim.path,
                        instance=inst,
                        contract=str(contract),
                        role=str(prim.attrs.get(pre + "role") or ""),
                        cardinality=str(prim.attrs.get(pre + "cardinality") or "one"),
                        failure_policy=str(prim.attrs.get(pre + "failurePolicy") or "required"),
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


def resolve(surfaces: Dict[str, Surface]) -> Resolution:
    """Bind every requirement to offers, by contract identity alone."""
    res = Resolution()

    catalogue: List[Tuple[str, Offer]] = [
        (asset, o) for asset, s in sorted(surfaces.items()) for o in s.offers if o.public
    ]

    for consumer, surface in sorted(surfaces.items()):
        for req in surface.requires:
            ref = "%s:%s" % (req.path, req.instance)
            name, major = req.key
            candidates = [
                (a, o) for a, o in catalogue
                if a != consumer and o.key == (name, major)
                and (not req.role or o.role == req.role)
            ]

            if not candidates:
                # Failure policy is declared, not exceptional.
                loose = [(a, o) for a, o in catalogue
                         if a != consumer and o.key[0] == name and o.key[1] != major]
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
    return out


def summarise(violations: Sequence[Violation]) -> str:
    if not violations:
        return "compatible"
    return "breaking: %d violation%s" % (len(violations), "" if len(violations) == 1 else "s")
