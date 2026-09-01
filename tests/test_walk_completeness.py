import pytest

pxr = pytest.importorskip("pxr")
from pxr import Sdf

from deps.walk import ARC, ASSET_ATTR, INTERNAL, walk_layer


def _layer(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return Sdf.Layer.FindOrOpen(str(p))


def test_internal_reference_recorded(tmp_path):
    layer = _layer(tmp_path, "a.usda", """#usda 1.0

def Xform "root"
{
    def Xform "proto"
    {
    }
    def Xform "copy" (
        prepend references = </root/proto>
    )
    {
    }
}
""")
    rec = walk_layer(layer)
    internal = [e for e in rec.edges if e.kind == INTERNAL]
    assert len(internal) == 1
    assert internal[0].src_prim == "/root/copy"
    assert internal[0].target == "/root/proto"


def test_deleted_rel_target_recorded_as_deleted(tmp_path):
    # Create a layer with a deleted relationship target using the Sdf API
    layer_path = str(tmp_path / "b.usda")
    layer = Sdf.Layer.CreateNew(layer_path)

    root_spec = Sdf.CreatePrimInLayer(layer, "/root")

    # Create the relationship by adding it to the spec
    target_path = Sdf.Path("/root/Looks/m")
    rel_spec = Sdf.RelationshipSpec(root_spec, "material:binding")

    # Add the deleted item to the relationship's targetPathList
    rel_spec.targetPathList.deletedItems.append(target_path)

    layer.Save()
    layer = Sdf.Layer.FindOrOpen(layer_path)

    rec = walk_layer(layer)
    dels = [e for e in rec.edges if e.deleted]
    assert len(dels) == 1
    assert dels[0].target == "/root/Looks/m"
    assert dels[0].name == "material:binding"


def test_clips_asset_paths_recorded(tmp_path):
    layer = _layer(tmp_path, "c.usda", """#usda 1.0

def Xform "root" (
    clips = {
        dictionary default = {
            asset[] assetPaths = [@./clip.001.usd@, @./clip.002.usd@]
        }
    }
)
{
}
""")
    rec = walk_layer(layer)
    clips = [e for e in rec.edges if e.kind == ASSET_ATTR and e.name == "clips"]
    assert sorted(e.target for e in clips) == ["./clip.001.usd", "./clip.002.usd"]


def test_cache_version_bumped():
    from deps.graph import CACHE_VERSION
    assert CACHE_VERSION == 2
