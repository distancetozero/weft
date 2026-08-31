from pathlib import Path

import pytest

from jitsd.contracts import (Surface, check_compatibility, extract_text,
                             resolve, split_contract)

EX = Path(__file__).resolve().parents[1] / "examples"


def surf(name):
    return extract_text((EX / ("%s.iface.usda" % name)).read_text())


def test_split_contract():
    assert split_contract("Mount@2") == ("Mount", 2)
    assert split_contract("Mount") == ("Mount", 0)


def test_extracts_offers_and_requirements():
    chassis, wheelset = surf("chassis"), surf("wheelset")
    assert len(chassis.offers) == 5 and not chassis.requires
    assert {o.role for o in chassis.offers} == {"wheelHub", "panelClip"}

    assert not wheelset.offers and len(wheelset.requires) == 1
    req = wheelset.requires[0]
    assert (req.contract, req.role, req.cardinality) == ("Mount@2", "wheelHub", "many")


def test_binds_by_contract_not_by_path():
    res = resolve({"chassis": surf("chassis"), "wheelset": surf("wheelset")})
    assert res.ok
    (b,) = res.bindings
    assert b.consumer == "wheelset" and len(b.providers) == 4
    # The consumer's own declaration names no provider anywhere. Check the
    # authored data, not the prose: the comments discuss the chassis on purpose.
    code = "\n".join(
        line for line in (EX / "wheelset.iface.usda").read_text().splitlines()
        if not line.lstrip().startswith("#")
    )
    assert "chassis" not in code


def test_role_narrows_the_match():
    """The panelClip must not be offered to something asking for a wheelHub."""
    res = resolve({"chassis": surf("chassis"), "wheelset": surf("wheelset")})
    (b,) = res.bindings
    assert all("aeroRail" not in p for p in b.providers)


def test_cardinality_one_with_many_candidates_is_ambiguous():
    wheelset = surf("wheelset")
    wheelset.requires[0].cardinality = "one"
    res = resolve({"chassis": surf("chassis"), "wheelset": wheelset})
    assert not res.ok
    assert "ambiguous" in res.diagnostics[0].message


def test_failure_policy_decides_severity():
    """aero is substitutable, wheelset is required: same absence, different outcome."""
    res = resolve({"wheelset": surf("wheelset"), "aero": surf("aero")})
    by_consumer = {d.consumer: d.severity for d in res.diagnostics}
    assert by_consumer["wheelset"] == "error"
    assert by_consumer["aero"] == "warning"
    assert not res.ok


def test_move_inside_the_envelope_is_compatible():
    old = surf("chassis")
    new = surf("chassis")
    hub = next(o for o in new.offers if o.path.endswith("hubFL"))
    hub.frame = (hub.frame[0] + 0.0003, hub.frame[1], hub.frame[2])
    assert check_compatibility(old, new) == []


def test_move_outside_the_envelope_is_breaking():
    old = surf("chassis")
    new = surf("chassis")
    hub = next(o for o in new.offers if o.path.endswith("hubFL"))
    hub.frame = (hub.frame[0] + 0.003, hub.frame[1], hub.frame[2])
    (v,) = check_compatibility(old, new)
    assert v.kind == "envelope" and v.offer.endswith("hubFL")


def test_removing_an_offer_is_breaking():
    old = surf("chassis")
    new = Surface(offers=[o for o in old.offers if not o.path.endswith("aeroRail")])
    (v,) = check_compatibility(old, new)
    assert v.kind == "removed"


def test_major_bump_is_breaking():
    old = surf("chassis")
    new = surf("chassis")
    for o in new.offers:
        o.contract = "Mount@3"
    assert all(v.kind == "major-bump" for v in check_compatibility(old, new))


def test_tightening_the_envelope_is_breaking():
    old = surf("chassis")
    new = surf("chassis")
    for o in new.offers:
        o.envelope_linear /= 10.0
    vs = check_compatibility(old, new)
    assert vs and all(v.kind == "envelope-tightened" for v in vs)


def test_adding_an_offer_is_compatible():
    old = surf("chassis")
    new = surf("chassis")
    extra = surf("chassis").offers[0]
    extra.path = "/chassis/mounts/hubSpare"
    new.offers.append(extra)
    assert check_compatibility(old, new) == []


def test_surface_round_trips_through_json_form():
    s = surf("chassis")
    assert Surface.from_dict(s.to_dict()).offers[0].frame == s.offers[0].frame
