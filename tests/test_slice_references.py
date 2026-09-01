"""Slice closure over USD reference edges, for assets that declare no contracts.

Found on ALab: not one of 4,296 layers declares a contract, so a closure that
walks only contract edges pulls nothing, and the receipt -- whose whole job is
to preview cost before loading -- reported 765 B for an asset that needs 11
layers and 6 textures. These tests pin the fix.
"""

from __future__ import annotations

import textwrap

import pytest

from jitsd.ledger import Repo
from jitsd.slice import SliceSpec, resolve_slice, receipt


def _repo(tmp_path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.init()
    return r


def _usda(tmp_path, name, text):
    p = tmp_path / ("%s.usda" % name)
    p.write_text(textwrap.dedent(text).lstrip())
    return p


def test_save_records_the_source_path(tmp_path):
    r = _repo(tmp_path)
    p = _usda(tmp_path, "solo", '#usda 1.0\n\ndef Xform "S"\n{\n}\n')
    rev = r.save("solo", p, "t")
    assert rev.source and rev.source.endswith("solo.usda")
    assert r.ledger.read_revision("solo", rev.rev).source == rev.source


def test_closure_without_pxr_is_contracts_only(tmp_path, monkeypatch):
    """Rung 1 must keep working with no pxr: fewer edges, nothing false."""
    import builtins
    real_import = builtins.__import__

    def no_deps(name, *a, **k):
        if name == "deps" or name.startswith("deps."):
            raise ImportError("simulated: no pxr")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_deps)
    r = _repo(tmp_path)
    r.save("a", _usda(tmp_path, "a", '#usda 1.0\n\ndef Xform "A"\n{\n}\n'), "t")
    res = resolve_slice(r, SliceSpec(seeds=["a"], channel="wip"))
    assert [m.asset for m in res.members] == ["a"]
    assert res.untracked == []


@pytest.mark.skipif(pytest.importorskip("pxr", reason="needs usd-core") is None,
                    reason="needs usd-core")
def test_reference_to_a_tracked_asset_joins_the_closure(tmp_path):
    r = _repo(tmp_path)
    mats = _usda(tmp_path, "mats", '''
        #usda 1.0

        def Scope "Looks"
        {
            def Material "Steel"
            {
            }
        }
    ''')
    car = _usda(tmp_path, "car", '''
        #usda 1.0

        def Xform "Car" (
            prepend references = @./mats.usda@</Looks>
        )
        {
        }
    ''')
    r.save("mats", mats, "t")
    r.save("car", car, "t")

    res = resolve_slice(r, SliceSpec(seeds=["car"], channel="wip"))
    names = {m.asset: m for m in res.members}
    assert set(names) == {"car", "mats"}
    assert names["mats"].provenance.kind == "closure"
    # Provenance names the KIND of relationship, not a catch-all: this one is
    # a composition arc, and closure can be told to follow it or not.
    assert "usd:arc" in names["mats"].provenance.detail
    assert res.untracked == []


@pytest.mark.skipif(pytest.importorskip("pxr", reason="needs usd-core") is None,
                    reason="needs usd-core")
def test_reference_to_an_untracked_file_is_costed_not_hidden(tmp_path):
    """The receipt must count bytes the member requires, tracked or not."""
    r = _repo(tmp_path)
    loose = _usda(tmp_path, "loose", '#usda 1.0\n\ndef Xform "L"\n{\n    double pad = 1\n}\n')
    car = _usda(tmp_path, "car", '''
        #usda 1.0

        def Xform "Car" (
            prepend references = @./loose.usda@</L>
        )
        {
        }
    ''')
    r.save("car", car, "t")           # loose.usda is deliberately NOT saved

    res = resolve_slice(r, SliceSpec(seeds=["car"], channel="wip"))
    assert [m.asset for m in res.members] == ["car"]
    assert len(res.untracked) == 1
    assert res.untracked[0].path.endswith("loose.usda")
    assert res.untracked[0].size == loose.stat().st_size
    assert res.untracked_bytes() > 0
    text = receipt(res)
    assert "untracked" in text and "loose" not in text.split("untracked")[0]


@pytest.mark.skipif(pytest.importorskip("pxr", reason="needs usd-core") is None,
                    reason="needs usd-core")
def test_reference_closure_respects_depth(tmp_path):
    r = _repo(tmp_path)
    c = _usda(tmp_path, "c", '#usda 1.0\n\ndef Xform "C"\n{\n}\n')
    b = _usda(tmp_path, "b", '#usda 1.0\n\ndef Xform "B" (\n    prepend references = @./c.usda@</C>\n)\n{\n}\n')
    a = _usda(tmp_path, "a", '#usda 1.0\n\ndef Xform "A" (\n    prepend references = @./b.usda@</B>\n)\n{\n}\n')
    for n, p in (("c", c), ("b", b), ("a", a)):
        r.save(n, p, "t")

    full = resolve_slice(r, SliceSpec(seeds=["a"], channel="wip"))
    assert {m.asset for m in full.members} == {"a", "b", "c"}

    shallow = resolve_slice(r, SliceSpec(seeds=["a"], channel="wip", depth=1))
    assert {m.asset for m in shallow.members} == {"a", "b"}
    assert any(x.asset == "c" for x in shallow.boundary)
