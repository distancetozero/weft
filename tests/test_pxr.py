"""Everything weft emits must open in real USD.

These tests are the difference between "the shape fits USD" as an argument and
as a fact. They skip when pxr is absent -- rung 1 must run with no dependencies
-- but they are the reason four USD syntax bugs were found, one of them in the
revision writer.
"""

import glob
import random
from pathlib import Path

import pytest

pytest.importorskip("pxr")

from pxr import Sdf, Usd  # noqa: E402

from weft.generators import vehicle  # noqa: F401,E402
from weft.ledger import Repo  # noqa: E402
from weft.query import compile_query, parse_query  # noqa: E402
from weft.usda import parse, parse_file  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def open_or_fail(text: str, label: str):
    layer = Sdf.Layer.CreateAnonymous(".usda")
    assert layer.ImportFromString(text), "%s: USD rejected the layer" % label
    return layer


# -- authored files -------------------------------------------------------

@pytest.mark.parametrize("path", sorted(
    glob.glob(str(ROOT / "examples" / "*.usda"))
    + glob.glob(str(ROOT / "specs" / "*.usda"))
    + glob.glob(str(ROOT / "specs" / "*" / "*.usda"))))
def test_authored_layers_open_in_usd(path):
    assert Sdf.Layer.FindOrOpen(path) is not None


# -- everything the code writes -------------------------------------------

def test_generator_backed_revision_opens(tmp_path):
    r = Repo(tmp_path)
    r.init()
    r.declare("chassis", "chassis@1.0.0", None, "tester")
    text = (r.ledger._revdir("chassis") / "v001.usda").read_text()
    layer = open_or_fail(text, "generator revision")
    spec = layer.GetPrimAtPath("/chassis")
    assert list(spec.GetInfo("apiSchemas").GetAddedOrExplicitItems()) == ["WeftGeneratorAPI"]


def test_payload_backed_revision_opens(tmp_path):
    """`payload` is prim metadata, not an attribute. Emitting it in the prim
    body produced a layer real USD refused -- and the demo never covered it."""
    r = Repo(tmp_path)
    r.init()
    p = tmp_path / "a.bin"
    p.write_bytes(random.Random(1).randbytes(20_000))
    rev = r.save("propA", p, "tester")
    text = (r.ledger._revdir("propA") / "v001.usda").read_text()
    layer = open_or_fail(text, "payload revision")
    spec = layer.GetPrimAtPath("/propA")
    paths = [x.assetPath for x in spec.GetInfo("payload").GetAddedOrExplicitItems()]
    assert paths == ["weft:obj/sha256:%s" % rev.blob]


def test_baseline_layer_opens(tmp_path):
    r = Repo(tmp_path)
    r.init()
    r.declare("chassis", "chassis@1.0.0", None, "tester")
    r.promote("chassis", "v001", "approved")
    b = r.cut_baseline(label="review")
    text = (r.ledger.baselines_dir / ("%s.usda" % b.number)).read_text()
    layer = open_or_fail(text, "baseline")
    pins = layer.GetPrimAtPath("/World").GetInfo("customData")["weft__pins"]
    assert dict(pins) == {"chassis": "v001"}


@pytest.mark.parametrize("context", ["hero", "review", "proxy", "engineering", "collision"])
def test_compiled_stages_open_and_carry_geometry(tmp_path, context):
    r = Repo(tmp_path)
    r.init()
    for a, g in (("chassis", "chassis@1.0.0"), ("wheelset", "wheelset@1.0.0")):
        r.declare(a, g, None, "tester")
        r.promote(a, "v001", "approved")
    q = parse_query(parse((ROOT / "examples" / "shot.usda").read_text()))
    c = compile_query(r, q, context=context)

    layer = open_or_fail(c.stage, "stage(%s)" % context)
    stage = Usd.Stage.Open(layer)
    meshes = [p for p in stage.Traverse() if p.GetTypeName() == "Mesh"]
    assert len(meshes) == (6 if context == "engineering" else 5)
    for m in meshes:
        pts = m.GetAttribute("points").Get()
        counts = m.GetAttribute("faceVertexCounts").Get()
        idx = m.GetAttribute("faceVertexIndices").Get()
        assert pts and counts and idx
        assert sum(counts) == len(idx), "face indices must match the face counts"
        assert max(idx) < len(pts), "index out of range for the point list"


def test_usd_agrees_with_our_computed_bounds(tmp_path):
    """Check our cheap bounds against USD's own extent computation."""
    from pxr import UsdGeom

    r = Repo(tmp_path)
    r.init()
    for a, g in (("chassis", "chassis@1.0.0"), ("wheelset", "wheelset@1.0.0")):
        r.declare(a, g, None, "tester")
        r.promote(a, "v001", "approved")
    q = parse_query(parse((ROOT / "examples" / "shot.usda").read_text()))
    c = compile_query(r, q, context="hero")

    stage = Usd.Stage.Open(open_or_fail(c.stage, "stage"))
    cache = UsdGeom.BBoxCache(Usd.TimeCode.Default(), [UsdGeom.Tokens.default_])
    box = cache.ComputeWorldBound(stage.GetPrimAtPath("/World")).ComputeAlignedRange()
    lo, hi = c.scene_bounds
    # Ours must be conservative: it may be larger, never smaller.
    for i in range(3):
        assert lo[i] <= box.GetMin()[i] + 1e-6
        assert hi[i] >= box.GetMax()[i] - 1e-6


# -- backend agreement ----------------------------------------------------

@pytest.mark.parametrize("path", sorted(glob.glob(str(ROOT / "examples" / "*.usda"))))
def test_both_reader_backends_agree(path):
    """A silent divergence would mean an interface that reads differently
    depending on what happens to be installed."""
    a = parse_file(Path(path))
    b = parse_file(Path(path), force_fallback=True)
    shape = lambda l: {p.path: (sorted(p.api_schemas), p.attrs) for p in l.walk()}
    assert shape(a) == shape(b)
    assert a.meta.get("customLayerData") == b.meta.get("customLayerData")
