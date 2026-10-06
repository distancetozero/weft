import pytest

from weft.ask import Seed, parse_seed


def test_bare_glob_is_name_plane():
    s = parse_seed("chemistry_bottle01*")
    assert (s.plane, s.value) == ("name", "chemistry_bottle01*")


def test_identity_and_occurrence():
    assert parse_seed("id:hero-car") == Seed("identity", "", "hero-car", "id:hero-car")
    s = parse_seed("id:occ:weld-47")
    assert (s.plane, s.key, s.value) == ("identity", "occ", "weld-47")


def test_contract_planes():
    assert parse_seed("role:propSocket").key == "role"
    assert parse_seed("offers:Mount").key == "offers"
    assert parse_seed("requires:Mount@1").value == "Mount@1"


def test_where_equality_and_metric():
    s = parse_seed("where:finish=translucent")
    assert (s.plane, s.key, s.value) == ("attr", "finish", "translucent")
    # ~/& stay reserved; a comparison on a non-metric key is rejected; a bare
    # key still wants attr=value. (Numeric metric comparisons on a real metric
    # parse -- see tests/test_data.py::test_parse_metric_predicate.)
    for bad, pat in (("where:finish~glass", "reserved"),
                     ("where:count>3", "numeric metric|not one"),
                     ("where:finish", "wants")):
        with pytest.raises(ValueError, match=pat):
            parse_seed(bad)


def test_spatial_seeds():
    s = parse_seed("within:0,0,0,10,3,10")
    assert s.plane == "spatial" and s.key == "within"
    s = parse_seed("near:id:rack-R42,5")
    assert s.plane == "spatial" and s.key == "near" and s.value == "id:rack-R42,5"
    with pytest.raises(ValueError, match="wants"):
        parse_seed("within:1,2,3")


def test_path_fallback():
    assert parse_seed("path:/root/shelf01/x").value == "/root/shelf01/x"


def test_spatial_non_numeric_raises_wants():
    with pytest.raises(ValueError, match="wants"):
        parse_seed("within:0,0,0,10,3,abc")
    with pytest.raises(ValueError, match="wants"):
        parse_seed("near:id:rack-R42,abc")
