import os
import pytest

pxr = pytest.importorskip("pxr")

from jitsd.manifest import (digest, layer_hashes, mask_paths, read_document,
                            to_document, verify, write_mask)
from jitsd.pull import pull

CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
    }
    def Xform "bottle_0001"
    {
        rel material:binding = </root/Looks/glass>
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


def test_document_records_evaluation_inputs(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"], depth=3)
    layer_hashes(p)
    doc = to_document(p)
    d = read_document(doc)
    assert d["context"]["hash"]                      # raw file -> content hash
    assert d["asks"] == ["bottle_*"]
    assert d["follow"] == ["material:binding"]
    assert d["depth"] == 3
    assert d["members"][0]["path"] == "/root/Looks/glass"
    assert all(h for _, h in d["layers"])
    assert d["digest"] == digest(d)


def test_verify_clean_manifest(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"])
    layer_hashes(p)
    assert verify(to_document(p)) == []


def test_verify_catches_vacuous_member(ctx):
    p = pull(ctx, ["bottle_*"], follow=["material:binding"])
    layer_hashes(p)
    from jitsd.pull import PullMember
    p.members.append(PullMember("/root/no_such_prim", "seed"))
    findings = verify(to_document(p))
    assert any("no_such_prim" in f and "does not resolve" in f for f in findings)


def test_verify_catches_layer_drift(ctx, tmp_path):
    p = pull(ctx, ["bottle_*"])
    layer_hashes(p)
    doc = to_document(p)
    with open(ctx, "a") as fh:
        fh.write("\n# drift\n")
    findings = verify(doc)
    assert any("hash" in f for f in findings)


def test_mask_file(ctx, tmp_path):
    p = pull(ctx, ["bottle_*"])
    f = tmp_path / "pull.mask"
    write_mask(p, f)
    assert f.read_text().splitlines() == mask_paths(p)


def test_manifest_context_path_is_portable_across_cwd(tmp_path, monkeypatch):
    """A manifest emitted while cwd is where the context was pulled from
    must still verify cleanly after cwd changes -- the recorded context
    path must not be relative to a cwd that no longer applies."""
    (tmp_path / "ctx.usda").write_text(CTX)
    monkeypatch.chdir(tmp_path)
    p = pull("ctx.usda", ["bottle_*"], follow=["material:binding"])
    layer_hashes(p)
    doc = to_document(p)

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert verify(doc) == []


def test_verify_reports_missing_context_instead_of_crashing(ctx, tmp_path):
    p = pull(ctx, ["bottle_*"])
    layer_hashes(p)
    doc = to_document(p)
    os.remove(ctx)
    findings = verify(doc)   # must NOT raise
    assert any("missing" in f for f in findings)
