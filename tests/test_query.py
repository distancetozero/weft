import random
from pathlib import Path

import pytest

from weft.generators import vehicle  # noqa: F401
from weft.ledger import Repo
from weft.query import compile_query, context_for, parse_query
from weft.usda import parse

SHOT = Path(__file__).resolve().parents[1] / "examples" / "shot.usda"


def _repo(tmp_path):
    r = Repo(tmp_path)
    r.init()
    r.declare("chassis", "chassis@1.0.0", None, "tester")
    r.declare("wheelset", "wheelset@1.0.0", None, "tester")
    r.promote("chassis", "v001", "approved")
    r.promote("wheelset", "v001", "approved")
    return r


def test_parses_a_query_document():
    q = parse_query(parse(SHOT.read_text()))
    assert q.label == "sq040_sh0120" and q.context == "review"
    assert {i.asset for i in q.instances} == {"chassis", "wheelset"}
    body = next(i for i in q.instances if i.asset == "chassis")
    assert body.params["wheelbase"] == pytest.approx(2.84)


def test_compiles_and_binds_by_contract(tmp_path):
    r = _repo(tmp_path)
    c = compile_query(r, parse_query(parse(SHOT.read_text())))
    assert c.ok
    (b,) = c.resolution.bindings
    # Consumers are keyed by instance PATH, not by asset and not by leaf
    # name: two instances of one asset are distinct consumers, and two
    # instances sharing a leaf name under different parents must not collide.
    assert b.consumer.endswith("car_wheels") and len(b.providers) == 4
    assert all("car_body" in p for p in b.providers)
    assert c.stage.count("def Mesh") == 5           # 1 body + 4 wheels
    assert c.pins == {"chassis": "v001", "wheelset": "v001"}


def test_wheels_follow_a_chassis_parameter_change(tmp_path):
    """The scenario this project opened with. The wheelset is never edited and
    never names the chassis; its placement follows a computed mount point."""
    import re

    r = _repo(tmp_path)
    text = SHOT.read_text()

    def wheel_x(src):
        c = compile_query(r, parse_query(parse(src)), context="proxy")
        blocks = re.findall(r'def Mesh "wheel_\d"\s*\{\s*point3f\[\] points = \[(.*?)\]',
                            c.stage, re.S)
        out = []
        for blk in blocks:
            xs = [float(m.group(1)) for m in
                  re.finditer(r"\(([-\d.e+]+),", blk)]
            out.append(round(sum(xs) / len(xs), 3))
        return sorted(set(abs(v) for v in out))

    assert wheel_x(text) == [pytest.approx(1.42)]
    longer = text.replace("jitsd:param:wheelbase = 2.84", "jitsd:param:wheelbase = 3.30")
    assert wheel_x(longer) == [pytest.approx(1.65)]


def test_same_query_different_contexts_differ(tmp_path):
    r = _repo(tmp_path)
    q = parse_query(parse(SHOT.read_text()))
    out = {name: compile_query(r, q, context=name)
           for name in ("hero", "review", "proxy", "engineering", "collision")}

    digests = {name: c.digest for name, c in out.items()}
    assert len(set(digests.values())) == 5, "each context must compile differently"

    # engineering is a different derivation, not a coarser one.
    assert out["engineering"].stage.count("def Mesh") == 6
    assert "batteryCell" in out["engineering"].stage
    for name in ("hero", "review", "proxy", "collision"):
        assert "batteryCell" not in out[name].stage


def test_compilation_is_deterministic(tmp_path):
    r = _repo(tmp_path)
    q = parse_query(parse(SHOT.read_text()))
    a = compile_query(r, q, context="hero")
    b = compile_query(r, q, context="hero")
    assert a.stage == b.stage and a.digest == b.digest


def test_phase_a_needs_no_geometry(tmp_path):
    """Bindings and bounds resolve with nothing generated."""
    r = _repo(tmp_path)
    q = parse_query(parse(SHOT.read_text()))
    a = compile_query(r, q, geometry=False)
    assert a.ok and len(a.resolution.bindings) == 1
    assert a.scene_bounds is not None
    assert "def Mesh" not in a.stage


def test_a_stored_payload_cannot_be_parameterised(tmp_path):
    r = _repo(tmp_path)
    p = tmp_path / "blob.bin"
    p.write_bytes(random.Random(1).randbytes(1000))
    r.save("chassis", p, "tester")           # replaces the generator revision
    r.promote("chassis", "v002", "approved", force=True)
    # shot.usda passes wheelbase to the chassis instance; a constant refuses it.
    with pytest.raises(ValueError, match="cannot be parameterised"):
        compile_query(r, parse_query(parse(SHOT.read_text())))


def test_a_stored_payload_compiles_as_a_constant(tmp_path):
    """Constants are functions: a blob-backed member emits a payload arc."""
    r = _repo(tmp_path)
    p = tmp_path / "blob.bin"
    p.write_bytes(random.Random(2).randbytes(1000))
    rev = r.save("propA", p, "tester")
    r.promote("propA", "v001", "approved")
    src = """#usda 1.0
(
    customLayerData = { string jitsd__context = "proxy" }
)
def Xform "S"
{
    def Xform "propA" ( prepend apiSchemas = ["JitsdInstanceAPI"] )
    {
        uniform token jitsd:instance:asset = "propA"
    }
}
"""
    c = compile_query(r, parse_query(parse(src)))
    assert c.ok
    assert "prepend payload = @jitsd:obj/sha256:%s@" % rev.blob in c.stage


def test_unknown_context_is_rejected():
    with pytest.raises(KeyError):
        context_for("nope")


def test_two_instances_of_one_asset_are_separate_consumers(tmp_path):
    r = _repo(tmp_path)
    src = '''#usda 1.0
(
    customLayerData = { string jitsd__context = "proxy" }
)
def Xform "Twin"
{
    def Xform "carA" ( prepend apiSchemas = ["JitsdInstanceAPI"] )
    {
        uniform token jitsd:instance:asset = "chassis"
        uniform double jitsd:param:wheelbase = 2.60
    }
    def Xform "wheelsA" ( prepend apiSchemas = ["JitsdInstanceAPI"] )
    {
        uniform token jitsd:instance:asset = "wheelset"
    }
    def Xform "wheelsB" ( prepend apiSchemas = ["JitsdInstanceAPI"] )
    {
        uniform token jitsd:instance:asset = "wheelset"
        uniform double jitsd:param:diameter = 0.80
    }
}
'''
    c = compile_query(r, parse_query(parse(src)))
    assert c.ok
    consumers = sorted(b.consumer for b in c.resolution.bindings)
    assert consumers == ["/Twin/wheelsA", "/Twin/wheelsB"]
    assert c.stage.count("def Mesh") == 9   # 1 body + 4 + 4 wheels
