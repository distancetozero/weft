"""The cross-call pull cache (weft/pullcache.py): a repeated pull of the same
expression against an unchanged context is a hit (no stage open); any real edit
to a consulted layer makes it stale. pxr-gated."""
import os

import pytest

SCENE = """#usda 1.0
( defaultPrim = "root" )
def Xform "root"
{
    def Xform "a"
    {
        def Mesh "m"
        {
            point3f[] points = [(0, 0, 0), (1, 0, 0), (1, 1, 0)]
            int[] faceVertexCounts = [3]
            int[] faceVertexIndices = [0, 1, 2]
        }
    }
    def Xform "b"
    {
    }
}
"""


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    Usd = pytest.importorskip("pxr.Usd")
    monkeypatch.setenv("WEFT_CACHE", str(tmp_path / "cache"))
    f = tmp_path / "scene.usda"
    f.write_text(SCENE)
    return str(f)


def test_miss_then_hit_same_members(ctx):
    from weft.pull import pull
    p1 = pull(ctx, ["path:/root/a"], cache=True)
    assert p1.accounting.get("cache") == "miss"
    m1 = sorted(m.path for m in p1.members)

    p2 = pull(ctx, ["path:/root/a"], cache=True)
    assert p2.accounting.get("cache") == "hit"           # served from cache
    assert sorted(m.path for m in p2.members) == m1       # identical result


def test_hit_matches_cold_pull(ctx):
    from weft.pull import pull
    cold = sorted(m.path for m in pull(ctx, ["path:/root/a"], cache=False).members)
    pull(ctx, ["path:/root/a"], cache=True)               # populate
    hot = sorted(m.path for m in pull(ctx, ["path:/root/a"], cache=True).members)
    assert hot == cold                                    # cache changes nothing but speed


def test_edit_invalidates(ctx):
    from weft.pull import pull
    pull(ctx, ["path:/root/a"], cache=True)               # miss -> stored
    assert pull(ctx, ["path:/root/a"], cache=True).accounting.get("cache") == "hit"
    # edit the layer: size + mtime change -> stat signature no longer matches
    with open(ctx, "a") as fh:
        fh.write('\ndef Xform "c" {}\n')
    assert pull(ctx, ["path:/root/a"], cache=True).accounting.get("cache") == "miss"


def test_different_expression_misses(ctx):
    from weft.pull import pull
    pull(ctx, ["path:/root/a"], cache=True)
    # a different seed is a different key -> its own miss, not a's hit
    assert pull(ctx, ["path:/root/b"], cache=True).accounting.get("cache") == "miss"


def test_cache_off_has_no_cache_field(ctx):
    from weft.pull import pull
    p = pull(ctx, ["path:/root/a"], cache=False)
    assert "cache" not in p.accounting
