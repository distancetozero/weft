import random
from pathlib import Path

import pytest

from weft.generators import vehicle  # noqa: F401
from weft.ledger import Repo
from weft.query import compile_query, parse_query
from weft.slice import (Overlay, SliceSpec, emit_query_document, read_spec,
                         resolve_slice)
from weft.usda import parse

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _repo(tmp_path):
    r = Repo(tmp_path)
    r.init()
    r.declare("chassis", "chassis@1.0.0", None, "alice")
    r.declare("wheelset", "wheelset@1.0.0", None, "bob")
    blob = tmp_path / "b.bin"
    blob.write_bytes(random.Random(1).randbytes(200_000))
    r.save("glass_building", blob, "carol")
    aero = tmp_path / "a.bin"
    aero.write_bytes(random.Random(2).randbytes(50_000))
    r.save("aero", aero, "alice", interface=EXAMPLES / "aero.iface.usda")
    for a in ("chassis", "wheelset", "glass_building", "aero"):
        r.promote(a, "v001", "approved")
    return r


def _slice(repo, **kw):
    return resolve_slice(repo, SliceSpec(**kw))


def members(result):
    return {m.asset: m for m in result.members}


# -- seeds -----------------------------------------------------------------

def test_name_and_glob_seeds(tmp_path):
    r = _repo(tmp_path)
    assert set(members(_slice(r, seeds=["wheelset"], closure=[]))) == {"wheelset"}
    assert set(members(_slice(r, seeds=["*e*se*"], closure=[]))) == {"wheelset"}


def test_contract_and_role_seeds(tmp_path):
    r = _repo(tmp_path)
    assert set(members(_slice(r, seeds=["provides:Mount@2"], closure=[]))) == {"chassis"}
    assert set(members(_slice(r, seeds=["requires:Mount@2"], closure=[]))) == {"wheelset", "aero"}
    assert set(members(_slice(r, seeds=["role:wheelHub"], closure=[]))) == {"chassis"}


def test_author_seed(tmp_path):
    r = _repo(tmp_path)
    assert set(members(_slice(r, seeds=["author:alice"], closure=[]))) == {"chassis", "aero"}


def test_spatial_seed_uses_declared_bounds(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["box:1.0,0,0,3,2,2"], closure=[])
    # chassis bounds reach x=1.87; wheelset bounds sit near the origin;
    # blob-backed assets declare no bounds and honestly cannot answer.
    assert set(members(res)) == {"chassis"}


def test_changed_since_seed(tmp_path):
    r = _repo(tmp_path)
    b = r.cut_baseline(label="before")
    r.declare("chassis", "chassis@1.0.0", {"wheelbase": 3.1}, "alice")
    # A 26 cm wheelbase change moves the hubs far outside their envelope, so
    # the gate refuses -- correctly. Force it, as a deliberate breaking change.
    r.promote("chassis", "v002", "approved", force=True)
    res = _slice(r, seeds=["changed-since:%s" % b.number], closure=[])
    assert set(members(res)) == {"chassis"}


# -- closure ---------------------------------------------------------------

def test_needs_closure_pulls_required_providers(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["wheelset"])
    m = members(res)
    assert set(m) == {"wheelset", "chassis"}
    assert m["chassis"].provenance.kind == "closure"
    assert "needs Mount@2 <- wheelset" in m["chassis"].provenance.detail


def test_substitutable_goes_to_boundary_not_membership(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["aero"])
    assert set(members(res)) == {"aero"}
    (b,) = res.boundary
    assert b.asset == "chassis" and "substitutable" in b.why_excluded

    pulled = _slice(r, seeds=["aero"], include_optional=True)
    assert set(members(pulled)) == {"aero", "chassis"}


def test_feeds_closure_is_opt_in(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["provides:Mount@2"], closure=["needs", "feeds"])
    assert set(members(res)) == {"chassis", "wheelset", "aero"}
    assert set(members(_slice(r, seeds=["provides:Mount@2"]))) == {"chassis"}


# -- overlays --------------------------------------------------------------

def test_pin_carries_attribution_and_participates_in_closure(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["glass_building"],
                 pins=[Overlay("wheelset", "dana", "hero foreground")])
    m = members(res)
    assert m["wheelset"].provenance.kind == "pin"
    assert m["wheelset"].provenance.author == "dana"
    assert m["wheelset"].provenance.detail == "hero foreground"
    # the pin's own needs-closure ran:
    assert "chassis" in m


def test_omit_excludes_and_surfaces_the_consequence(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["wheelset"],
                 omits=[Overlay("chassis", "dana", "too heavy")])
    assert set(members(res)) == {"wheelset"}
    assert not res.ok
    assert any("provider chassis is omitted" in d for d in res.diagnostics)


def test_every_member_has_provenance(tmp_path):
    r = _repo(tmp_path)
    res = _slice(r, seeds=["requires:Mount@2"],
                 pins=[Overlay("glass_building", "dana", "reflects")])
    for m in res.members:
        assert m.provenance.kind in ("seed", "closure", "pin")
        assert m.provenance.detail


# -- round trip ------------------------------------------------------------

def test_slice_round_trips_through_a_query_document(tmp_path):
    r = _repo(tmp_path)
    spec = SliceSpec(seeds=["wheelset"], label="sh0120_light",
                     pins=[Overlay("glass_building", "dana", "reflects into shot")])
    res = resolve_slice(r, spec)
    doc = emit_query_document(res)

    out = tmp_path / "slice.usda"
    out.write_text(doc)
    spec2 = read_spec(out)
    assert spec2 == spec

    res2 = resolve_slice(r, spec2)
    assert {m.asset for m in res2.members} == {m.asset for m in res.members}


def test_emitted_slice_compiles_and_opens(tmp_path):
    r = _repo(tmp_path)
    res = resolve_slice(r, SliceSpec(
        seeds=["wheelset"],
        pins=[Overlay("glass_building", "dana", "reflects into shot")]))
    c = compile_query(r, parse_query(parse(emit_query_document(res))))
    assert c.ok
    assert "prepend payload = @weft:obj/sha256:" in c.stage   # the constant
    assert c.stage.count("def Mesh") == 5                       # body + 4 wheels
