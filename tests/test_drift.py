"""Tests for weft/drift.py -- capture/verify of drift receipts.

Mirrors the pxr-gated style of tests/test_threadgraph.py: a synthetic-stage
suite shaped like a miniature ALab checkout (entity/<asset>/<asset>.usda,
interface files, assetInfo on every placement), plus a WEFT_ALAB-gated
acceptance run against the real workbench that pins the proven translucent
member count and proves the capture -> edit -> verify loop end to end."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

import pytest

pxr = pytest.importorskip("pxr")

from weft import drift  # noqa: E402

# -- synthetic-stage suite ---------------------------------------------------
#
# A miniature ALab-shaped tree in tmp_path: the scene lives at
# entity/scene01/scene01.usda so _alab_root_from_stage derives tmp_path as
# the checkout root, asset_a is bound translucent (two instances), asset_b
# matte (one instance).

ASSET = """#usda 1.0
(
    defaultPrim = "%(name)s"
)

def Xform "%(name)s" (
    kind = "component"
)
{
}
"""

PLACEMENT = """        def Xform "%(prim)s" (
            kind = "component"
            assetInfo = {
                string name = "%(asset)s"
                string entityType = "setpiece"
            }
            prepend references = @../%(asset)s/%(asset)s.usda@
        )
        {
        }
"""

SCENE_HEAD = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root" (
    kind = "assembly"
    assetInfo = {
        string name = "scene01"
    }
)
{
    def Xform "%(group)s"
    {
"""

SCENE_TAIL = """    }
}
"""


def _scene_text(placements, group="shelf01"):
    body = "".join(PLACEMENT % {"prim": p, "asset": a} for p, a in placements)
    return (SCENE_HEAD % {"group": group}) + body + SCENE_TAIL


DEFAULT_PLACEMENTS = [
    ("asset_a_0001", "asset_a"),
    ("asset_a_0002", "asset_a"),
    ("asset_b_0001", "asset_b"),
]

RULE = {"kind": "facet", "facet": "finish", "value": "translucent"}


def _write_tree(root, a_finish="translucent", b_finish="matte"):
    """Lay down assets + interfaces + the default scene; return its path."""
    for asset, finish in (("asset_a", a_finish), ("asset_b", b_finish)):
        d = root / "entity" / asset
        (d / "interface").mkdir(parents=True)
        (d / ("%s.usda" % asset)).write_text(ASSET % {"name": asset})
        (d / "interface" / ("%s_interface.usda" % asset)).write_text(
            'uniform token weft:bind:finish = "%s"\n' % finish)
    scene_dir = root / "entity" / "scene01"
    scene_dir.mkdir(parents=True)
    scene = scene_dir / "scene01.usda"
    scene.write_text(_scene_text(DEFAULT_PLACEMENTS))
    return scene


def _open(path):
    from pxr import Usd
    return Usd.Stage.Open(str(path))


@pytest.fixture
def tree(tmp_path):
    return _write_tree(tmp_path)


def _variant_stage(scene, placements, group="shelf01"):
    """A sibling scene file (same entity/scene01/ dir, so the same derived
    checkout root) with a different placement list -- the 'changed stage'
    verify is pointed at."""
    v = scene.parent / "scene01_v2.usda"
    v.write_text(_scene_text(placements, group=group))
    return _open(v)


def test_capture_members_signatures_and_roundtrip(tree, tmp_path):
    receipt = drift.capture(_open(tree), RULE, name="translucent-set")

    assert [m["signature"]["path"] for m in receipt.members] == [
        "/root/shelf01/asset_a_0001",
        "/root/shelf01/asset_a_0002",
    ]
    for i, m in enumerate(receipt.members):
        sig = m["signature"]
        assert sig["asset"] == "asset_a"
        assert sig["asset_ref"] == "entity/asset_a/asset_a.usda"
        assert sig["type"] == "setpiece"
        assert sig["where"] == ["/root/shelf01", i]
        assert sig["id_hint"] is None
        assert sig["tier"] == "A"
        assert m["read"] == {"finish": "translucent"}
        assert m["fingerprint"] == hashlib.sha256(
            b'{"finish":"translucent"}').hexdigest()

    # the merkle root is a pure function of the member fingerprints
    again = drift.capture(_open(tree), RULE, name="translucent-set")
    assert again.merkle_root == receipt.merkle_root

    p = tmp_path / "out" / "translucent-set.weft"
    drift.write_receipt(receipt, str(p))
    assert drift.read_receipt(str(p)) == receipt


def test_noop_verify_is_clean(tree):
    stage = _open(tree)
    receipt = drift.capture(stage, RULE, name="t")
    report = drift.verify(receipt, stage)
    assert report.clean
    assert (report.renamed == report.changed == report.departed
            == report.arrived == report.ambiguous == [])
    assert report.merkle_root_after == report.merkle_root_before


def test_rename_is_inert(tree):
    receipt = drift.capture(_open(tree), RULE, name="t")
    renamed = _variant_stage(tree, [
        ("asset_a_0001", "asset_a"),
        ("asset_a_0042", "asset_a"),   # was asset_a_0002
        ("asset_b_0001", "asset_b"),
    ])
    report = drift.verify(receipt, renamed)
    assert report.clean
    assert report.changed == report.departed == report.arrived == []
    assert len(report.renamed) == 1
    f = report.renamed[0]
    assert f["old_path"] == "/root/shelf01/asset_a_0002"
    assert f["new_path"] == "/root/shelf01/asset_a_0042"
    assert f["tier"] == "A"
    # same read, same fingerprints -> the digest did not move either
    assert report.merkle_root_after == report.merkle_root_before


def test_finish_change_is_meaning_changing(tree, tmp_path):
    stage = _open(tree)
    receipt = drift.capture(stage, RULE, name="t")
    # flip the asset's bound finish at its source, the interface file
    (tmp_path / "entity" / "asset_a" / "interface" / "asset_a_interface.usda"
     ).write_text('uniform token weft:bind:finish = "matte"\n')
    report = drift.verify(receipt, stage)
    assert not report.clean
    assert report.renamed == report.departed == report.arrived == []
    assert len(report.changed) == 2
    for f in report.changed:
        assert f["old"] == {"finish": "translucent"}
        assert f["new"] == {"finish": "matte"}
        assert f["tier"] == "A"
    assert report.merkle_root_after != report.merkle_root_before


def test_new_instance_arrives(tree):
    receipt = drift.capture(_open(tree), RULE, name="t")
    grown = _variant_stage(tree, DEFAULT_PLACEMENTS + [
        ("asset_a_0003", "asset_a"),
    ])
    report = drift.verify(receipt, grown)
    assert not report.clean
    assert report.renamed == report.changed == report.departed == []
    assert len(report.arrived) == 1
    a = report.arrived[0]
    assert a["signature"]["path"] == "/root/shelf01/asset_a_0003"
    assert a["signature"]["asset"] == "asset_a"
    assert a["read"] == {"finish": "translucent"}


def test_unrelated_edit_is_clean(tree, tmp_path):
    stage = _open(tree)
    receipt = drift.capture(stage, RULE, name="t")
    # touch the matte asset's interface -- an attribute the rule never read
    iface = tmp_path / "entity" / "asset_b" / "interface" / "asset_b_interface.usda"
    iface.write_text(iface.read_text()
                     + "uniform color3f primvars:tint = (1, 0, 0)\n")
    report = drift.verify(receipt, stage)
    assert report.clean
    assert (report.renamed == report.changed == report.departed
            == report.arrived == report.ambiguous == [])
    assert report.merkle_root_after == report.merkle_root_before


def test_reorg_beyond_where_is_ambiguous_not_asserted(tree):
    receipt = drift.capture(_open(tree), RULE, name="t")
    # move every instance to a new group: path AND the `where` locator both
    # miss, and with two unmatched same-asset instances on each side no
    # honest pairing exists
    moved = _variant_stage(tree, DEFAULT_PLACEMENTS, group="shelf02")
    report = drift.verify(receipt, moved)
    assert len(report.ambiguous) == 2
    for f in report.ambiguous:
        assert sorted(f["candidates"]) == [
            "/root/shelf02/asset_a_0001",
            "/root/shelf02/asset_a_0002",
        ]
    # reported, not asserted: no false changed/departed, and the ambiguous
    # candidates are not double-counted as arrivals
    assert report.changed == report.departed == report.arrived == []
    assert report.clean   # a warning, not a failure


# -- acceptance: the real ALab workbench ----------------------------------

ALAB = os.environ.get("WEFT_ALAB") or os.environ.get("JITSD_ALAB")
WORKBENCH = "entity/lab_workbench01/lab_workbench01.usda"

# chemistry_beaker01's two placements in the proven translucent mask
# (tests/test_alab_pull.py pins all 26)
BEAKER01_PATHS = {
    "/root/workbench01/benchtop02/chemistry_beaker01_0001",
    "/root/workbench01/benchtop03/chemistry_beaker01_0002",
}


@pytest.mark.skipif(not ALAB, reason="set WEFT_ALAB to the ALab directory to run acceptance")
def test_capture_verify_loop_on_real_alab_workbench():
    stage = _open(os.path.join(ALAB, WORKBENCH))
    receipt = drift.capture(stage, RULE, name="translucent-set")

    # the spike's proven member set: 26 placements over 8 assets, Tier A
    assert len(receipt.members) == 26
    assert {m["signature"]["tier"] for m in receipt.members} == {"A"}
    assert {m["signature"]["asset"] for m in receipt.members} == {
        "chemistry_beaker01", "chemistry_beaker02", "chemistry_beaker03",
        "chemistry_bottle01", "decor_bottle_soda01", "decor_glass01",
        "stationary_set_square01", "stationary_set_square02"}
    assert BEAKER01_PATHS <= {m["signature"]["path"] for m in receipt.members}
    assert receipt.merkle_root == drift.capture(
        stage, RULE, name="translucent-set").merkle_root

    # unchanged stage -> clean
    report = drift.verify(receipt, stage)
    assert report.clean
    assert (report.renamed == report.changed == report.departed
            == report.arrived == report.ambiguous == [])

    # a copy of the checkout with ONE interface finish flipped -> exactly
    # that asset's members changed, nothing else. cp -c clones (APFS) so
    # the 3 GB tree costs neither time nor disk; plain -R is the fallback.
    parent = tempfile.mkdtemp(dir=os.path.dirname(ALAB.rstrip("/")))
    try:
        clone = os.path.join(parent, "ALab")
        if subprocess.run(["cp", "-Rc", ALAB, clone],
                          capture_output=True).returncode != 0:
            shutil.copytree(ALAB, clone)
        iface = os.path.join(clone, "entity", "chemistry_beaker01",
                             "interface", "chemistry_beaker01_interface.usda")
        with open(iface) as fh:
            text = fh.read()
        assert '"translucent"' in text
        with open(iface, "w") as fh:
            fh.write(text.replace('"translucent"', '"matte"'))

        flipped = _open(os.path.join(clone, WORKBENCH))
        report = drift.verify(receipt, flipped)
        assert not report.clean
        assert report.renamed == report.departed == report.arrived == []
        assert {f["member"]["path"] for f in report.changed} == BEAKER01_PATHS
        for f in report.changed:
            assert f["old"] == {"finish": "translucent"}
            assert f["new"] == {"finish": "matte"}
        assert report.merkle_root_after != report.merkle_root_before
    finally:
        shutil.rmtree(parent, ignore_errors=True)
