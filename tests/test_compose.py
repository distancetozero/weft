"""The resolver brain: expression -> surgical layer (compose.py).

The grammar tests are pure Python; everything touching a stage is
pxr-gated; the ALab acceptance additionally wants WEFT_ALAB."""

import json
import os

import pytest

from weft.compose import Expression, parse_expression

# -- expression grammar (no pxr) ------------------------------------------

def test_expression_seeds_and_directives():
    e = parse_expression("where:finish=translucent follow:Mount depth:3")
    assert e.seeds == ["where:finish=translucent"]
    assert e.follow == ["Mount"]
    assert e.depth == 3


def test_expression_uri_query_form():
    # `&`-separated: a weft:// URI's query string is a valid expression
    e = parse_expression("bottle_0001&follow:Mount,material:binding&depth:2")
    assert e.seeds == ["bottle_0001"]
    assert e.follow == ["Mount", "material:binding"]
    assert e.depth == 2


def test_expression_follow_accumulates():
    e = parse_expression("a follow:Mount follow:up:electrical:feeds*8")
    assert e.follow == ["Mount", "up:electrical:feeds*8"]


def test_expression_no_seeds_is_loud():
    with pytest.raises(ValueError, match="no seeds"):
        parse_expression("follow:Mount depth:2")


def test_expression_bad_depth_is_loud():
    with pytest.raises(ValueError, match="depth"):
        parse_expression("a depth:many")
    with pytest.raises(ValueError, match="twice"):
        parse_expression("a depth:1 depth:2")


def test_expression_reserved_syntax_is_loud():
    with pytest.raises(ValueError):                 # ask.py reserves ~ in where:
        parse_expression("where:finish~glass")
    with pytest.raises(ValueError):                 # follow.py reserves ->
        parse_expression("a follow:Mount->Shelf")


# -- surgical layer on a small scene (pxr) --------------------------------

pxr = pytest.importorskip("pxr")

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
        def Material "steel"
        {
        }
    }
    def Xform "shelf01"
    {
        def Xform "bottle_0001"
        {
            rel material:binding = </root/Looks/glass>
            rel custom:pairedWith = </root/shelf01/bottle_0002>
        }
        def Xform "bottle_0002"
        {
            rel material:binding = </root/Looks/steel>
        }
        def Xform "crate_0001"
        {
        }
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


def _prims(stage):
    return {p.GetPath().pathString for p in stage.Traverse()}


def _masked(context, paths):
    from pxr import Usd
    return Usd.Stage.OpenMasked(context, Usd.StagePopulationMask(paths))


def test_surgical_layer_composes_to_exactly_the_closure(ctx, tmp_path):
    from pxr import Usd
    from weft.compose import compose
    from weft.manifest import mask_paths

    out = str(tmp_path / "surgical.usda")
    c = compose(ctx, "bottle_0001 follow:material:binding", out=out)

    paths = mask_paths(c.pull)
    assert set(paths) == {"/root/shelf01/bottle_0001", "/root/Looks/glass"}
    # the written layer, reopened, composes to EXACTLY the masked stage:
    # members plus their spine ancestors, nothing else
    got = _prims(Usd.Stage.Open(out))
    assert got == _prims(_masked(ctx, paths))
    assert got == {"/root", "/root/Looks", "/root/Looks/glass",
                   "/root/shelf01", "/root/shelf01/bottle_0001"}
    # the surgical subset: unfollowed siblings are absent
    assert "/root/shelf01/bottle_0002" not in got
    assert "/root/shelf01/crate_0001" not in got
    assert "/root/Looks/steel" not in got
    assert c.prim_count == len(got)
    assert c.member_count == 2


def test_expression_string_drives_the_same_closure_as_pull(ctx):
    from weft.compose import compose
    from weft.pull import pull

    c = compose(ctx, "bottle_0001&follow:custom:pairedWith,material:binding&depth:2")
    p = pull(ctx, ["bottle_0001"],
             follow=["custom:pairedWith", "material:binding"], depth=2)
    assert [m.path for m in c.pull.members] == [m.path for m in p.members]


def test_layer_provenance_is_stamped(ctx, tmp_path):
    from pxr import Sdf
    from weft.compose import compose

    out = str(tmp_path / "surgical.usda")
    compose(ctx, "bottle_0001 follow:material:binding", out=out)
    cd = Sdf.Layer.FindOrOpen(out).customLayerData
    rec = json.loads(cd["weft__compose"])
    assert rec["context"] == os.path.abspath(ctx)
    assert rec["seeds"] == ["bottle_0001"]
    assert rec["follow"] == ["material:binding"]
    assert "/root/Looks/glass" in rec["members"]


def test_composed_pull_reverifies_through_manifest(ctx):
    from weft.compose import compose
    from weft.manifest import layer_hashes, to_document, verify

    c = compose(ctx, "bottle_0001 follow:material:binding")
    layer_hashes(c.pull)
    assert verify(to_document(c.pull)) == []


def test_empty_match_is_loud(ctx):
    from weft.compose import compose
    with pytest.raises(ValueError, match="matched nothing"):
        compose(ctx, "no_such_prim_anywhere")


def test_cli_compose_writes_layer_and_manifest(ctx, tmp_path, capsys):
    from pxr import Usd
    from weft.cli import main
    from weft.manifest import verify

    out = str(tmp_path / "surgical.usda")
    man = str(tmp_path / "surgical_manifest.usda")
    rc = main(["compose", "bottle_0001 follow:material:binding",
               "--context", ctx, "-o", out, "--out-manifest", man])
    assert rc == 0
    text = capsys.readouterr().out
    assert "surgical stage 5 prims" in text
    assert len(_prims(Usd.Stage.Open(out))) == 5
    assert verify(open(man).read()) == []


def test_cli_open_print_only(ctx, capsys):
    from weft.cli import main
    rc = main(["open", "bottle_0001 follow:material:binding",
               "--context", ctx, "--print-only"])
    assert rc == 0
    text = capsys.readouterr().out
    # members ride in pull's sorted-by-path order
    assert "--mask /root/Looks/glass,/root/shelf01/bottle_0001" in text


# -- ALab acceptance ------------------------------------------------------

ALAB = os.environ.get("WEFT_ALAB") or os.environ.get("JITSD_ALAB")

needs_alab = pytest.mark.skipif(
    not ALAB, reason="set WEFT_ALAB to the ALab directory to run acceptance")


@needs_alab
def test_alab_workbench_surgical_stage(tmp_path):
    from pxr import Usd
    from weft.compose import compose
    from weft.manifest import layer_hashes, mask_paths, to_document, verify

    ctx = os.path.join(ALAB, "entity/lab_workbench01/lab_workbench01.usda")
    out = str(tmp_path / "translucent.usda")
    c = compose(ctx, "where:finish=translucent", out=out)

    # the pull closure is the spike's 26 placements (test_alab_pull.py
    # asserts them path-for-path); here: the SURGICAL LAYER's composed
    # prim set equals the masked open of the original context, exactly
    paths = mask_paths(c.pull)
    assert len(paths) == 26
    got = _prims(Usd.Stage.Open(out))
    want = _prims(_masked(ctx, paths))
    assert got == want
    assert all(p in got for p in paths)

    # and it re-verifies clean through the existing manifest
    layer_hashes(c.pull)
    assert verify(to_document(c.pull)) == []
