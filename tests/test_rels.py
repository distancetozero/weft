"""authored_relationship_kinds: discover the native relationship kinds on a
stage (what you can --follow), with no weft declaration. pxr-gated."""
import pytest

SCENE = """#usda 1.0
( defaultPrim = "root" )
def Xform "root"
{
    def Xform "wall"
    {
        def Xform "outlet01"
        {
        }
    }
    def Xform "bench"
    {
        def Xform "device_a"
        {
            custom rel electrical:feeds = </root/wall/outlet01>
        }
        def Xform "device_b"
        {
            custom rel electrical:feeds = </root/wall/outlet01>
        }
        def Xform "lamp"
        {
            custom rel electrical:feeds = </root/wall/outlet01>
            custom rel sits:on = </root/bench>
        }
    }
}
"""


@pytest.fixture
def stage(tmp_path):
    Usd = pytest.importorskip("pxr.Usd")
    f = tmp_path / "s.usda"
    f.write_text(SCENE)
    return Usd.Stage.Open(str(f), Usd.Stage.LoadNone)


def test_discovers_native_rels_with_counts(stage):
    from weft.pull import authored_relationship_kinds
    kinds = authored_relationship_kinds(stage)
    assert kinds.get("electrical:feeds") == 3     # device_a, device_b, lamp
    assert kinds.get("sits:on") == 1              # lamp only
    # no declaration was involved; these are plain authored USD rels
