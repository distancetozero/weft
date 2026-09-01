"""Consumer re-evaluation: the exemplar half of the promotion gate.

check_compatibility() asks whether a provider kept its own promise. This asks
the other question, the one the docs call one of the two or three most
valuable properties in the design: rebuild the world with the candidate pinned,
re-bind every consumer that touches it, and compare each consumer's MANIFEST
before and after.

A manifest is a consumer's relational-plane result: for each requirement, the
offers it bound to and every binding attribute of each. Two manifests either
match or they do not, attribute by attribute, each by its own kind's rule and
the CONSUMER's tolerance -- falling back to the provider's envelope only where
the consumer declared nothing. The envelope is what the provider asserts; this
is what gets measured.

Nothing here reads geometry. It is a phase-A computation over surfaces, which
is why it is also the slice's impact preview: "your edit moves this mount --
1 consumer inside your slice, 2 outside." Same function, called from both.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .contracts import (
    ANGULAR, EXACT, SET, SPATIAL, Attribute, Offer, Resolution, Surface,
    _angular_delta, resolve,
)

Manifest = Dict[str, Dict[str, Dict[str, Attribute]]]   # req -> offer -> attr


@dataclass
class ConsumerViolation:
    consumer: str
    requirement: str       # "path:instance", possibly "#exemplar" suffixed
    kind: str              # unresolved | rebound | moved | rotated | changed | narrowed
    offer: str             # "asset/path" or "" for requirement-level
    detail: str
    breaking: bool = True

    def __str__(self) -> str:
        where = (" on %s" % self.offer) if self.offer else ""
        return "%-10s %s %s%s: %s" % (self.kind, self.consumer, self.requirement,
                                       where, self.detail)


@dataclass
class ReEvaluation:
    consumers: List[str]
    violations: List[ConsumerViolation]
    proof: str                       # hash over every matched manifest
    changed: List[str] = field(default_factory=list)  # consumers whose manifest changed at all

    @property
    def breaking(self) -> List[ConsumerViolation]:
        return [v for v in self.violations if v.breaking]

    @property
    def ok(self) -> bool:
        return not self.breaking


# -- manifests -------------------------------------------------------------

def _offer_index(surfaces: Dict[str, Surface]) -> Dict[str, Offer]:
    return {"%s%s" % (asset, o.path): o
            for asset, s in surfaces.items() for o in s.offers}


def manifests(surfaces: Dict[str, Surface], res: Resolution,
              consumers: Iterable[str]) -> Dict[str, Manifest]:
    """Each consumer's bound offers, with every attribute of each."""
    offers = _offer_index(surfaces)
    out: Dict[str, Manifest] = {c: {} for c in consumers}
    for b in res.bindings:
        if b.consumer not in out:
            continue
        per_req = out[b.consumer].setdefault(b.requirement, {})
        for key in b.providers:
            o = offers.get(key)
            if o is not None:
                per_req[key] = o.attributes()
    return out


def _serialisable(m: Manifest) -> Dict:
    return {req: {off: {a: {"kind": at.kind, "value": at.value}
                        for a, at in sorted(attrs.items())}
                  for off, attrs in sorted(offs.items())}
            for req, offs in sorted(m.items())}


def proof_of(matched: Dict[str, Manifest]) -> str:
    blob = json.dumps({c: _serialisable(m) for c, m in sorted(matched.items())},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


# -- comparison ------------------------------------------------------------

def _compare_attr(name: str, old: Attribute, new: Optional[Attribute],
                  tolerance: Optional[float]) -> Tuple[Optional[str], str, bool]:
    """(kind-of-violation or None, detail, breaking)."""
    if new is None:
        return "narrowed", "%s no longer declared" % name, True
    if old.kind in (SPATIAL, ANGULAR):
        limit = tolerance if tolerance is not None else (old.tolerance or 0.0)
        who = "consumer tolerates" if tolerance is not None else "provider promised"
        if old.kind == SPATIAL:
            d = math.dist(old.value, new.value)
            if d > limit:
                return "moved", "%s moved %.4g, %s %.4g" % (name, d, who, limit), True
        else:
            d = _angular_delta(old.value, new.value)
            if d > limit:
                return "rotated", "%s turned %.4g deg, %s %.4g" % (name, d, who, limit), True
        return None, "", False
    if old.kind == EXACT:
        if old.value != new.value:
            return "changed", "%s %r -> %r" % (name, old.value, new.value), True
        return None, "", False
    if old.kind == SET:
        lost = sorted(set(old.value) - set(new.value))
        if lost:
            return "narrowed", "%s no longer offers %s" % (name, ", ".join(lost)), True
        return None, "", False
    return None, "", False


def compare(consumer: str, req_ref: str, req_binds: Dict[str, Attribute],
            required: bool, old: Dict[str, Dict[str, Attribute]],
            new: Dict[str, Dict[str, Attribute]],
            view: Optional[Sequence[str]] = None) -> List[ConsumerViolation]:
    """One requirement's bindings before and after."""
    out: List[ConsumerViolation] = []
    old_keys, new_keys = set(old), set(new)

    for key in sorted(old_keys - new_keys):
        out.append(ConsumerViolation(
            consumer, req_ref, "rebound", key,
            "no longer bound to this offer", breaking=required))
    for key in sorted(new_keys - old_keys):
        out.append(ConsumerViolation(
            consumer, req_ref, "rebound", key,
            "now also bound to this offer", breaking=False))

    for key in sorted(old_keys & new_keys):
        o_attrs, n_attrs = old[key], new[key]
        for name, o_attr in sorted(o_attrs.items()):
            if view is not None and name not in view:
                continue
            # The consumer's own tolerance for this attribute, if it declared one.
            tol = req_binds[name].tolerance if name in req_binds else None
            kind, detail, breaking = _compare_attr(name, o_attr, n_attrs.get(name), tol)
            if kind:
                out.append(ConsumerViolation(consumer, req_ref, kind, key, detail,
                                             breaking=breaking and required))
    return out


# -- the gate --------------------------------------------------------------

def touching(res: Resolution, assets: Set[str]) -> Set[str]:
    """Consumers bound to any offer of the given providers."""
    out: Set[str] = set()
    for b in res.bindings:
        if any(p.split("/", 1)[0] in assets for p in b.providers):
            out.add(b.consumer)
    return out


def reevaluate(old_surfaces: Dict[str, Surface], new_surfaces: Dict[str, Surface],
               changed: Set[str], view: Optional[Sequence[str]] = None) -> ReEvaluation:
    """Re-bind every consumer touching `changed`, before and after, and diff.

    `old_surfaces` is the world in force; `new_surfaces` is the same world
    with the candidate revisions pinned. Consumers are anyone bound to a
    changed provider in either world -- so a candidate that newly captures a
    consumer (an added same-role offer making a cardinality-one requirement
    ambiguous) is caught, which the provider's self-check cannot see.
    """
    old_res = resolve(old_surfaces, view)
    new_res = resolve(new_surfaces, view)
    consumers = sorted((touching(old_res, changed) | touching(new_res, changed)) - changed)

    old_m = manifests(old_surfaces, old_res, consumers)
    new_m = manifests(new_surfaces, new_res, consumers)

    violations: List[ConsumerViolation] = []
    matched: Dict[str, Manifest] = {}
    changed_consumers: List[str] = []

    new_errors = {(d.consumer, d.requirement): d.message
                  for d in new_res.diagnostics if d.severity == "error"}

    for c in consumers:
        surface = new_surfaces.get(c) or old_surfaces.get(c) or Surface()
        before = len(violations)
        for r in surface.requires:
            ref = "%s:%s" % (r.path, r.instance)
            required = r.failure_policy == "required"
            was_bound = bool(old_m[c].get(ref))
            if (c, ref) in new_errors and was_bound:
                violations.append(ConsumerViolation(
                    c, ref, "unresolved", "", new_errors[(c, ref)], breaking=required))
                continue
            violations.extend(compare(c, ref, r.binds, required,
                                      old_m[c].get(ref, {}), new_m[c].get(ref, {}), view))
        if len(violations) > before:
            changed_consumers.append(c)
        else:
            matched[c] = new_m[c]

    return ReEvaluation(consumers=consumers, violations=violations,
                        proof=proof_of(matched), changed=changed_consumers)
