"""Acceptance: the spike's three asks, reproduced from one-line pulls on the
real ALab tree (spec section 11). Skips cleanly without JITSD_ALAB."""

import os

import pytest

pxr = pytest.importorskip("pxr")

ALAB = os.environ.get("JITSD_ALAB")
pytestmark = pytest.mark.skipif(
    not ALAB, reason="set JITSD_ALAB to the ALab directory to run acceptance")

WORKBENCH = "entity/lab_workbench01/lab_workbench01.usda"

TRANSLUCENT = ["chemistry_beaker01", "chemistry_beaker02", "chemistry_beaker03",
               "chemistry_bottle01", "decor_bottle_soda01", "decor_glass01",
               "stationary_set_square01", "stationary_set_square02"]

ASSEMBLY = ("fragment/assembly/assembly/lab_workbench01/"
            "assembly_assembly_lab_workbench01.usda")
PROVIDER = "lab_workbench01"


def _ctx():
    return os.path.join(ALAB, WORKBENCH)


def _needs_regen() -> bool:
    """The interface carries advisory carriers only once regenerated with
    carrier_rule="group-furniture". Cheap text check -- no stage open."""
    iface = os.path.join(
        ALAB, "entity", PROVIDER, "interface", "%s_interface.usda" % PROVIDER)
    if not os.path.exists(iface):
        return True
    text = open(iface).read()
    return "jitsd:offer:carrier" not in text or 'over "root"' not in text


@pytest.fixture(scope="module", autouse=True)
def _regenerated_interfaces():
    """Regenerate the workbench + placed-prop interfaces root-anchored
    (anchor="root") with advisory furniture carriers, mirroring
    examples/alab/poc.py's extraction -> write_interfaces path. Root-anchored
    overs compose onto the assembly's own /root placements; the
    asset-anchored interfaces checked into this tree from an earlier pass do
    not. Idempotent: skips entirely once already regenerated."""
    if not ALAB or not _needs_regen():
        return
    from jitsd.extract import (departments, finish as _finish,
                               materials as _materials, read_assembly,
                               write_interfaces)

    A = ALAB
    ex = read_assembly(os.path.join(A, ASSEMBLY), PROVIDER)
    asset_dirs = {a: os.path.join(A, "entity", a) for a in ex.assets
                  if os.path.isdir(os.path.join(A, "entity", a))}
    asset_dirs[PROVIDER] = os.path.join(A, "entity", PROVIDER)

    reps = {}
    for a, d in asset_dirs.items():
        if a == PROVIDER:
            continue
        depts = departments(os.path.join(d, "%s.usda" % a))
        if depts:
            reps[a] = depts

    look_by_asset = {}
    for a in ex.assets:
        lb = os.path.join(A, "fragment", "look", "surfacing", a, "render_high",
                          "binding", "look_surfacing_%s_render_high_binding" % a,
                          "render_high.usda")
        if os.path.exists(lb):
            look_by_asset[a] = lb

    import tempfile
    with tempfile.TemporaryDirectory() as scratch:
        # out_dir only backstops assets missing from `into_assets`; every
        # asset extracted here has an entity dir, so nothing lands there.
        write_interfaces(ex, scratch, envelope=1.0, tolerance_fraction=0.10,
                         represent=True, into_assets=asset_dirs,
                         look_by_asset=look_by_asset,
                         carrier_rule="group-furniture", anchor="root")


def test_ask_one_bottle():
    from jitsd.pull import pull
    p = pull(_ctx(), ["path:/root/shelf01/chemistry_bottle01_0004"])
    assert [m.path for m in p.members] == ["/root/shelf01/chemistry_bottle01_0004"]

    # the bare lexical form (name, not path) resolves to the same member
    q = pull(_ctx(), ["chemistry_bottle01_0004"])
    assert [m.path for m in q.members] == [m.path for m in p.members]


def test_ask_translucent_matches_spike_mask():
    from jitsd.pull import pull
    p = pull(_ctx(), ["where:finish=translucent"])
    paths = [m.path for m in p.members]
    # the spike's mask: 26 placements under /root, every one a placement of
    # one of the 8 translucent assets, no common ancestor below /root
    assert len(paths) == 26
    assert all(any(part.startswith(t) for t in TRANSLUCENT
                   for part in p_.split("/")) for p_ in paths)


def test_ask_mount_with_carrier():
    from jitsd.pull import pull
    p = pull(_ctx(), ["path:/root/shelf01/chemistry_bottle01_0004"],
             follow=["Mount"])
    paths = [m.path for m in p.members]
    assert "/root/shelf01/chemistry_bottle01_0004" in paths
    carriers = [x for x in paths if "furniture_" in x]
    assert carriers, "carrier rule must pull the shelf01 furniture"
    assert all("/shelf01/" in c or c.endswith("shelf01") for c in carriers)


def test_manifest_verifies():
    from jitsd.manifest import layer_hashes, to_document, verify
    from jitsd.pull import pull
    p = pull(_ctx(), ["where:finish=translucent"])
    layer_hashes(p)
    assert verify(to_document(p)) == []
