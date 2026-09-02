import pytest

pxr = pytest.importorskip("pxr")

from jitsd.cli import main
from jitsd.ledger import Repo
from jitsd.generators import vehicle as _vehicle  # noqa: F401  registers built-ins

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


def test_pull_rejects_malformed_ask_cleanly(tmp_path, capsys):
    """A malformed ask must fail with the grammar's own message, not a
    traceback -- the CLI/slice boundary is where failures become diagnostics."""
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    rc = main(["pull", "where:bad", "--context", str(ctx)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "where: wants attr=value" in err
    assert "Traceback" not in err


def test_who_rejects_malformed_ask_cleanly(tmp_path, capsys):
    ctx = tmp_path / "ctx.usda"
    ctx.write_text(CTX)
    rc = main(["who", "where:bad", "--context", str(ctx)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "who: where: wants attr=value" in err
    assert "Traceback" not in err


def test_who_depth_flag_reaches_second_hop(tmp_path, capsys):
    f = tmp_path / "chain.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "a"
    {
        rel c:next = </root/b>
    }
    def Xform "b"
    {
        rel c:next = </root/c>
    }
    def Xform "c"
    {
    }
}
""")
    rc = main(["who", "name:c", "--context", str(f), "--depth", "2"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "/root/b" in out and "/root/c" in out
    assert "/root/a" in out and "/root/b" in out


def test_pull_rejects_generator_backed_context(tmp_path, capsys, monkeypatch):
    """Pull must fail cleanly when context is generator-backed, not raise exception."""
    import os

    # Create a repo and declare a generator-backed asset
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    repo = Repo(repo_dir)
    repo.init()

    # Declare a generator-backed revision (no blob)
    rev = repo.declare("chassis", "chassis", {"wheelbase": 2.8}, "tester")
    repo.promote("chassis", rev.rev, "approved")

    # Change to repo directory so Repo.find() works
    monkeypatch.chdir(repo_dir)

    # Try to use it as a pull context
    rc = main(["pull", "x", "--context", "chassis"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "generator-backed" in err
