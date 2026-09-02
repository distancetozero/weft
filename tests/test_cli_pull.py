import pytest

pxr = pytest.importorskip("pxr")

from jitsd.cli import main

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


def test_pull_raw_file_emits_manifest_and_mask(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    out = tmp_path / "pull.usda"
    mask = tmp_path / "pull.mask"
    rc = main(["pull", "bottle_*", "--context", str(ctx),
               "--follow", "material:binding",
               "-o", str(out), "--mask-out", str(mask)])
    assert rc == 0
    text = capsys.readouterr().out
    assert "members (2)" in text
    assert "/root/Looks/glass" in mask.read_text().splitlines()
    from jitsd.manifest import read_document
    assert read_document(out.read_text())["follow"] == ["material:binding"]


def test_pull_verify_roundtrip(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    out = tmp_path / "pull.usda"
    assert main(["pull", "bottle_*", "--context", str(ctx), "-o", str(out)]) == 0
    assert main(["pull", "--verify", str(out)]) == 0
    ctx.write_text(CTX + "\n# drift\n")
    assert main(["pull", "--verify", str(out)]) == 1


def test_who_reports_chain(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    rc = main(["who", "name:glass", "--context", str(ctx)])
    assert rc == 0
    assert "material:binding" in capsys.readouterr().out
