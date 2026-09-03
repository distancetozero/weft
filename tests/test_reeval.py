"""Consumer re-evaluation: the exemplar half of the gate.

Each test names a case the provider's self-check cannot see, and asserts the
re-evaluation does. Fixtures are surfaces built directly, so nothing here
needs a repository or pxr; the last test goes through the whole promotion
path to prove the wiring.
"""

from __future__ import annotations

import pytest

from weft.contracts import (
    ANGULAR, EXACT, SET, SPATIAL, Attribute, Offer, Requirement, Surface,
    check_compatibility, extract_text, resolve,
)
from weft.reeval import reevaluate
from weft.ledger import BreakingChange, Repo


def _offer(path="/m", role="cup", frame=(0.0, 0.0, 0.0), env=1.0, **binds):
    return Offer(path=path, contract="Mount@1", role=role, frame=frame,
                 envelope_linear=env,
                 binds={k: v for k, v in binds.items()})


def _req(role="cup", cardinality="many", tolerance=None, **binds):
    b = dict(binds)
    if tolerance is not None:
        b["position"] = Attribute(SPATIAL, None, tolerance)
    return Requirement(path="/c", instance="mount", contract="Mount@1", role=role,
                       cardinality=cardinality, binds=b)


def _world(offers, req):
    return {"shelf": Surface(offers=offers), "cup": Surface(requires=[req])}


# -- measured, not asserted -------------------------------------------------

def test_consumer_tolerance_tighter_than_envelope_is_refused():
    """The provider kept its 1 cm promise. The consumer only tolerates 0.5."""
    old = _world([_offer(frame=(0, 0, 0), env=1.0)], _req(tolerance=0.5))
    new = _world([_offer(frame=(0, 0.7, 0), env=1.0)], _req(tolerance=0.5))
    assert check_compatibility(old["shelf"], new["shelf"]) == []   # self-check passes
    re = reevaluate(old, new, {"shelf"})
    assert not re.ok
    (v,) = re.breaking
    assert v.kind == "moved" and v.consumer == "cup"
    assert "consumer tolerates 0.5" in v.detail


def test_unstated_tolerance_trusts_the_envelope():
    old = _world([_offer(frame=(0, 0, 0), env=1.0)], _req())
    new = _world([_offer(frame=(0, 0.7, 0), env=1.0)], _req())
    assert reevaluate(old, new, {"shelf"}).ok


def test_matching_manifests_yield_a_stable_proof():
    old = _world([_offer()], _req())
    a = reevaluate(old, old, {"shelf"})
    b = reevaluate(old, old, {"shelf"})
    assert a.ok and a.proof and a.proof == b.proof


# -- what the self-check cannot see ------------------------------------------

def test_added_same_role_offer_breaks_a_cardinality_one_consumer():
    """Adding an offer is 'compatible' to the provider. It makes a consumer
    that expects exactly one ambiguous, and it stops resolving."""
    old = _world([_offer(path="/a")], _req(cardinality="one"))
    new = _world([_offer(path="/a"), _offer(path="/b")], _req(cardinality="one"))
    assert check_compatibility(old["shelf"], new["shelf"]) == []
    re = reevaluate(old, new, {"shelf"})
    assert [v.kind for v in re.breaking] == ["unresolved"]


def test_removed_binding_is_breaking_added_is_not():
    old = _world([_offer(path="/a"), _offer(path="/b")], _req())
    new = _world([_offer(path="/a"), _offer(path="/c")], _req())
    re = reevaluate(old, new, {"shelf"})
    kinds = {(v.offer, v.breaking) for v in re.violations if v.kind == "rebound"}
    assert ("shelf/b", True) in kinds
    assert ("shelf/c", False) in kinds


# -- binding on more than position ------------------------------------------

def test_material_is_a_binding_attribute():
    """A consumer constrained on material only binds where it matches, and a
    material change on the provider is a break for it."""
    glass = _offer(path="/g", material=Attribute(EXACT, "glass"))
    steel = _offer(path="/s", material=Attribute(EXACT, "steel"))
    req = _req(material=Attribute(EXACT, "glass"))
    res = resolve({"shelf": Surface(offers=[glass, steel]), "cup": Surface(requires=[req])})
    (b,) = res.bindings
    assert b.providers == ["shelf/g"]

    old = _world([glass], req)
    new = _world([_offer(path="/g", material=Attribute(EXACT, "steel"))], req)
    re = reevaluate(old, new, {"shelf"})
    assert [v.kind for v in re.breaking] == ["unresolved"]


def test_set_attribute_narrowing_breaks_a_consumer_that_needs_it():
    both = _offer(purposes=Attribute(SET, ["proxy", "render"]))
    req = _req(purposes=Attribute(SET, ["render"]))
    old = _world([both], req)
    new = _world([_offer(purposes=Attribute(SET, ["proxy"]))], req)
    re = reevaluate(old, new, {"shelf"})
    assert [v.kind for v in re.breaking] == ["unresolved"]   # no longer satisfies


def test_a_view_ignores_attributes_outside_it():
    """A context reading only position does not care that material changed."""
    req = _req(material=Attribute(EXACT, "glass"))
    old = _world([_offer(material=Attribute(EXACT, "glass"))], req)
    new = _world([_offer(material=Attribute(EXACT, "steel"))], req)
    assert not reevaluate(old, new, {"shelf"}).ok
    assert reevaluate(old, new, {"shelf"}, view=["position"]).ok


def test_attributes_round_trip_through_usda_and_json():
    src = '''#usda 1.0
def Xform "shelf" ( prepend apiSchemas = ["WeftOfferAPI"] )
{
    uniform token  weft:offer:contract = "Mount@1"
    uniform token  weft:mount:role     = "cup"
    uniform token  weft:bind:material  = "glass"
    uniform token[] weft:bind:purposes = ["render", "proxy"]
    uniform double weft:envelope:linear = 1
    double3 xformOp:translate = (1, 2, 3)
}
def Xform "cup" ( prepend apiSchemas = ["WeftRequireAPI:mount"] )
{
    uniform token  weft:require:mount:contract = "Mount@1"
    uniform token  weft:require:mount:role     = "cup"
    uniform token  weft:require:mount:bind:material = "glass"
    uniform double weft:require:mount:tolerance:linear = 0.25
}
'''
    s = extract_text(src)
    o, r = s.offers[0], s.requires[0]
    assert o.binds["material"].value == "glass"
    assert o.binds["purposes"].value == ["proxy", "render"]
    assert r.binds["material"].value == "glass"
    assert r.tolerance("position") == 0.25
    back = Surface.from_dict(s.to_dict())
    assert back.offers[0].binds["purposes"].kind == SET
    assert back.requires[0].tolerance("position") == 0.25


# -- through the real gate --------------------------------------------------

def test_promotion_refuses_on_consumer_tolerance(tmp_path):
    def iface(shelf_y, tol=0.5):
        return '''#usda 1.0
def Xform "shelf" ( prepend apiSchemas = ["WeftOfferAPI"] )
{
    uniform token weft:offer:contract = "Mount@1"
    uniform token weft:mount:role = "cup"
    uniform double weft:envelope:linear = 1
    double3 xformOp:translate = (0, %s, 0)
}
''' % shelf_y, '''#usda 1.0
def Xform "cup" ( prepend apiSchemas = ["WeftRequireAPI:mount"] )
{
    uniform token weft:require:mount:contract = "Mount@1"
    uniform token weft:require:mount:role = "cup"
    uniform double weft:require:mount:tolerance:linear = %s
}
''' % tol

    r = Repo(tmp_path / "repo")
    r.init()
    body = tmp_path / "body.usda"
    body.write_text('#usda 1.0\ndef Xform "x"\n{\n}\n')
    s0, c0 = iface(0.0)
    (tmp_path / "s0.usda").write_text(s0)
    (tmp_path / "c0.usda").write_text(c0)
    r.save("shelf", body, "t", interface=tmp_path / "s0.usda")
    r.save("cup", body, "t", interface=tmp_path / "c0.usda")
    r.promote("shelf", "v001", "approved")
    r.promote("cup", "v001", "approved")

    # 0.7 up: inside the provider's 1 cm envelope, past the cup's 0.5 tolerance
    s1, _ = iface(0.7)
    (tmp_path / "s1.usda").write_text(s1)
    body.write_text('#usda 1.0\ndef Xform "x"\n{\n    double v = 1\n}\n')
    r.save("shelf", body, "t", interface=tmp_path / "s1.usda")
    with pytest.raises(BreakingChange) as ei:
        r.promote("shelf", "@wip", "approved")
    kinds = [getattr(v, "kind", None) for v in ei.value.violations]
    assert "moved" in kinds and "envelope" not in kinds   # consumer caught it; provider did not
    assert r.ledger.channels("shelf")["approved"] == "v001"
