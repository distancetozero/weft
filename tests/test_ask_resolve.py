import pytest

pxr = pytest.importorskip("pxr")
from pxr import Usd

from jitsd.ask import resolve_seeds

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


def test_seed_matching_nothing_is_declared(stage):
    (r,) = resolve_seeds(stage, ["id:no-such"])
    assert r.paths == [] and "matched nothing" in r.note
