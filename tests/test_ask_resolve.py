import pytest

pxr = pytest.importorskip("pxr")
from pxr import Usd

from weft.ask import resolve_seeds

FIXTURE = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "shelf01"
    {
        def Xform "bottle_0001" (
            customData = { string "absent:id" = "hero-bottle" }
        )
        {
            float3[] extentsHint = [(-1, 0, -1), (1, 2, 1)]
            double3 xformOp:translate = (0, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform token finish = "translucent"
        }
        def Xform "bottle_0002"
        {
            float3[] extentsHint = [(-1, 0, -1), (1, 2, 1)]
            double3 xformOp:translate = (100, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
            uniform token finish = "opaque"
        }
        def Xform "crate_0001"
        {
        }
        def Xform "mount" (
            customData = { string "absent:id" = "bolt-m8" }
        )
        {
            uniform token weft:offer:contract = "Mount@1"
            uniform token weft:offer:role = "propSocket"
        }
        def Xform "fastener" (
            customData = { string "absent:id" = "bolt-m8" }
        )
        {
        }
        def Xform "sealed_container"
        {
            uniform token weft:bind:finish = "glossy"
            float rating = 1.5
        }
    }
}
"""


@pytest.fixture
def stage(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(FIXTURE)
    return Usd.Stage.Open(str(p), Usd.Stage.LoadNone)


def test_name_glob(stage):
    (r,) = resolve_seeds(stage, ["bottle_*"])
    assert r.mode == "lexical" and len(r.paths) == 2


def test_identity(stage):
    (r,) = resolve_seeds(stage, ["id:hero-bottle"])
    assert r.paths == ["/root/shelf01/bottle_0001"]
    assert r.mode == "identity"


def test_where_with_complement(stage):
    (r,) = resolve_seeds(stage, ["where:finish=translucent"])
    assert r.paths == ["/root/shelf01/bottle_0001"]
    assert r.matched == 1
    assert r.complement >= 1   # crate_0001 authors no finish


def test_within_box(stage):
    (r,) = resolve_seeds(stage, ["within:-5,-5,-5,5,5,5"])
    assert r.paths == ["/root/shelf01/bottle_0001"]   # 0002 sits at x=100
    assert r.mode == "spatial"
    assert r.complement >= 1   # crate has no extentsHint


def test_near_seed(stage):
    (r,) = resolve_seeds(stage, ["near:id:hero-bottle,10"])
    assert "/root/shelf01/bottle_0001" in r.paths
    assert "/root/shelf01/bottle_0002" not in r.paths


def test_path_exact_and_declared(stage):
    (r,) = resolve_seeds(stage, ["path:/root/shelf01/bottle_0002"])
    assert r.paths == ["/root/shelf01/bottle_0002"] and r.mode == "path"


def test_path_below_payload_kept_with_note(stage):
    (r,) = resolve_seeds(stage, ["path:/root/shelf01/ghost"])
    assert r.paths == ["/root/shelf01/ghost"]
    assert "not in composed world" in r.note


def test_path_glob_matches_full_paths(stage):
    (r,) = resolve_seeds(stage, ["path:/root/shelf01/bottle_*"])
    assert r.paths == ["/root/shelf01/bottle_0001", "/root/shelf01/bottle_0002"]
    assert r.mode == "path"


def test_path_glob_no_match_is_noted(stage):
    (r,) = resolve_seeds(stage, ["path:/root/shelf01/nope_*"])
    assert r.paths == []
    assert "matched nothing" in r.note


def test_seed_matching_nothing_is_declared(stage):
    (r,) = resolve_seeds(stage, ["id:no-such"])
    assert r.paths == [] and "matched nothing" in r.note


def test_contract_offers_resolution(stage):
    (r,) = resolve_seeds(stage, ["offers:Mount"])
    assert r.paths == ["/root/shelf01/mount"]
    assert r.mode == "contract"


def test_contract_role_resolution(stage):
    (r,) = resolve_seeds(stage, ["role:propSocket"])
    assert r.paths == ["/root/shelf01/mount"]
    assert r.mode == "contract"


def test_where_via_weft_bind_fallback(stage):
    (r,) = resolve_seeds(stage, ["where:finish=glossy"])
    assert r.paths == ["/root/shelf01/sealed_container"]
    assert r.mode == "attribute"


def test_type_identity_multi_match_note(stage):
    (r,) = resolve_seeds(stage, ["id:bolt-m8"])
    assert len(r.paths) == 2
    assert "type identity: 2" in r.note
    assert "placements" in r.note


def test_occurrence_ambiguity_note(stage):
    (r,) = resolve_seeds(stage, ["id:occ:bolt-m8"])
    assert len(r.paths) == 2
    assert "ambiguous" in r.note
    assert "occurrence id matches" in r.note


def test_typed_equality_float_match(stage):
    (r,) = resolve_seeds(stage, ["where:rating=1.50"])
    assert r.paths == ["/root/shelf01/sealed_container"]
    assert r.mode == "attribute"


def test_seed_and_reverse_edge_resolve_behind_unloaded_payload(tmp_path):
    """A prim that is genuinely COMPOSED (a non-payload layer authors an
    `over` opinion for it directly -- unlike `test_path_below_payload_kept
    _with_note` above, which never gets a real prim at all) can still have
    `IsLoaded() == False`, because ITS OWN path also carries an unloaded
    payload arc from another contributing layer. That is the ALab shape
    (Task 13 acceptance): an instanceable placement's composed root gets
    one opinion from the assembly (translate, attributes -- always
    available) and another from a payload-bearing modelling/variant layer
    contributing to the SAME path (heavy geometry -- gated on load). Usd's
    default traversal predicate requires UsdPrimIsLoaded, so plain
    `stage.Traverse()` drops such a prim entirely, silently, even though
    `GetPrimAtPath` resolves it fine and its non-payload attributes are
    fully composed. `resolve_seeds` (name and attribute planes) and
    `who()`'s reverse index (over `pull._reverse_index`) must find it
    anyway. Reverting the traversal predicate in `weft/ask.py` and
    `weft/pull.py` back to plain `stage.Traverse()` makes every assertion
    here fail (verified by hand; see task-13-report.md)."""
    from weft.pull import who

    (tmp_path / "inner.usda").write_text("""#usda 1.0
def "geo"
{
}
""")
    # A sublayer, weaker than ctx.usda's own root-level opinions but still
    # composing onto the SAME prim path as the payload-bearing "def" below
    # -- `over`, because the prim is already `def`'d elsewhere.
    (tmp_path / "extra.usda").write_text("""#usda 1.0

over "parent"
{
    over "child"
    {
        string myattr = "findme"
        rel custom:pairedWith = </external/target>
    }
}
""")
    ctx = tmp_path / "ctx.usda"
    ctx.write_text("""#usda 1.0
(
    subLayers = [
        @extra.usda@
    ]
)

def "parent" (
    prepend payload = @inner.usda@
)
{
    def "child"
    {
    }
}

def "external"
{
    def "target"
    {
    }
}
""")

    stage = Usd.Stage.Open(str(ctx), Usd.Stage.LoadNone)
    child = stage.GetPrimAtPath("/parent/child")
    # Sanity: this fixture reproduces the exact bug shape -- a real,
    # composed, non-abstract, defined, active prim that is still
    # IsLoaded() == False.
    assert child and child.IsDefined() and not child.IsLoaded()
    assert child.GetAttribute("myattr").Get() == "findme"

    (r,) = resolve_seeds(stage, ["child"])
    assert r.paths == ["/parent/child"], (
        "name seed must find a composed-but-unloaded prim")

    (r2,) = resolve_seeds(stage, ["where:myattr=findme"])
    assert r2.paths == ["/parent/child"], (
        "attribute seed must find a composed-but-unloaded prim")

    edges = who(str(ctx), ["path:/external/target"])
    assert ("/parent/child", "custom:pairedWith", "/external/target") in edges, (
        "_reverse_index must see an edge authored on a composed-but-"
        "unloaded source prim")


MAT_SCENE = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "mtl"
    {
        def Material "glass"
        {
        }
        def Material "steel"
        {
        }
    }

    def Mesh "a" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding:full = </root/mtl/glass>
    }

    def Mesh "b" (
        prepend apiSchemas = ["MaterialBindingAPI"]
    )
    {
        rel material:binding:full = </root/mtl/steel>
    }
}
"""


def test_material_selector_by_name(tmp_path):
    from pxr import Usd
    p = tmp_path / "m.usda"
    p.write_text(MAT_SCENE)
    st = Usd.Stage.Open(str(p), Usd.Stage.LoadAll)
    (r,) = resolve_seeds(st, ["material:glass"])
    assert r.paths == ["/root/a"] and r.mode == "material"


def test_material_selector_by_exact_path_and_glob(tmp_path):
    from pxr import Usd
    p = tmp_path / "m.usda"
    p.write_text(MAT_SCENE)
    st = Usd.Stage.Open(str(p), Usd.Stage.LoadAll)
    (r,) = resolve_seeds(st, ["material:/root/mtl/steel"])
    assert r.paths == ["/root/b"]
    (g,) = resolve_seeds(st, ["material:gl*"])
    assert g.paths == ["/root/a"]


def test_material_selector_no_match_is_noted(tmp_path):
    from pxr import Usd
    p = tmp_path / "m.usda"
    p.write_text(MAT_SCENE)
    st = Usd.Stage.Open(str(p), Usd.Stage.LoadAll)
    (r,) = resolve_seeds(st, ["material:nope"])
    assert r.paths == [] and "no prim bound" in r.note
