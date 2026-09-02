"""Extracting a contract surface from an existing assembly."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

pytest.importorskip("pxr")

from jitsd.contracts import extract_text, resolve  # noqa: E402
from jitsd.extract import (  # noqa: E402
    Extraction, Placement, consumer_interface, provider_interface,
    read_assembly, write_interfaces,
)
from jitsd.ledger import BreakingChange, Repo  # noqa: E402


def _assembly(tmp_path):
    for n in ("bottle01", "screw01"):
        (tmp_path / ("%s.usda" % n)).write_text(
            '#usda 1.0\n\ndef Xform "root"\n{\n}\n')
    p = tmp_path / "bench_assembly.usda"
    p.write_text(textwrap.dedent('''
        #usda 1.0

        def Xform "root"
        {
            def Xform "shelf01"
            {
                def Xform "bottle01_0004" (
                    prepend references = @./bottle01.usda@</root>
                )
                {
                    double3 xformOp:translate = (-3.4, 143.0, -36.8)
                }
                def Xform "bottle01_0005" (
                    prepend references = @./bottle01.usda@</root>
                )
                {
                    double3 xformOp:translate = (-17.7, 143.0, -30.2)
                }
            }
            def Xform "floor01"
            {
                def Xform "screw01_0008" (
                    prepend references = @./screw01.usda@</root>
                )
                {
                    double3 xformOp:translate = (120.8, 0.0, 31.6)
                }
            }
        }
    ''').lstrip())
    return p


def test_reads_placements_with_group_asset_and_frame(tmp_path):
    ex = read_assembly(str(_assembly(tmp_path)), "bench")
    assert ex.groups == ["floor01", "shelf01"]
    assert ex.assets == ["bottle01", "screw01"]
    by = {p.name: p for p in ex.placements}
    assert by["bottle01_0004"].asset == "bottle01"
    assert by["bottle01_0004"].translate == (-3.4, 143.0, -36.8)
    assert by["screw01_0008"].group == "floor01"


def test_emitted_interfaces_parse_and_bind(tmp_path):
    ex = read_assembly(str(_assembly(tmp_path)), "bench")
    prov = extract_text(provider_interface(ex, envelope=1.0))
    assert len(prov.offers) == 3
    assert {o.role for o in prov.offers} == {"bottle01", "screw01"}
    assert all(o.envelope_linear == 1.0 for o in prov.offers)
    assert any(o.frame == (-3.4, 143.0, -36.8) for o in prov.offers)

    cons = extract_text(consumer_interface("bottle01"))
    assert len(cons.requires) == 1 and cons.requires[0].role == "bottle01"
    assert cons.requires[0].cardinality == "many"

    res = resolve({"bench": prov, "bottle01": cons,
                   "screw01": extract_text(consumer_interface("screw01"))})
    assert res.ok
    providers = {b.consumer: len(b.providers) for b in res.bindings}
    assert providers == {"bottle01": 2, "screw01": 1}


def test_nudge_moves_only_that_group(tmp_path):
    ex = read_assembly(str(_assembly(tmp_path)), "bench")
    moved = extract_text(provider_interface(ex, nudge={"shelf01": (0.0, 3.0, 0.0)}))
    by = {o.path: o for o in moved.offers}
    assert by["/bench/shelf01/bottle01_0004"].frame == (-3.4, 146.0, -36.8)
    assert by["/bench/floor01/screw01_0008"].frame == (120.8, 0.0, 31.6)


def test_end_to_end_gate_refuses_a_moved_shelf(tmp_path):
    """The whole point: a real placement, moved past its envelope, is refused."""
    asm = _assembly(tmp_path)
    ex = read_assembly(str(asm), "bench")
    ifaces = write_interfaces(ex, str(tmp_path / "iface"), envelope=1.0)

    r = Repo(tmp_path / "repo")
    r.init()
    r.save("bench", asm, "t", interface=ifaces["bench"])
    for a in ex.assets:
        r.save(a, tmp_path / ("%s.usda" % a), "t", interface=ifaces[a])
        r.promote(a, "v001", "approved")
    r.promote("bench", "v001", "approved")
    assert r.bind(channel="approved").ok

    # compatible: half a centimetre, inside the 1 cm envelope
    ok_iface = tmp_path / "iface" / "bench.ok.usda"
    ok_iface.write_text(provider_interface(ex, envelope=1.0, nudge={"shelf01": (0, 0.5, 0)}))
    r.save("bench", asm, "t", interface=ok_iface)
    rev, forced = r.promote("bench", "@wip", "approved")
    assert rev == "v002" and forced == []

    # breaking: three centimetres, past it
    bad_iface = tmp_path / "iface" / "bench.bad.usda"
    bad_iface.write_text(provider_interface(ex, envelope=1.0, nudge={"shelf01": (0, 3.0, 0)}))
    r.save("bench", asm, "t", interface=bad_iface)
    with pytest.raises(BreakingChange) as ei:
        r.promote("bench", "@wip", "approved")
    # Both halves of the gate fire: the provider broke its promise (envelope),
    # and every consumer bound to those offers sees them move (moved).
    kinds = {v.kind for v in ei.value.violations}
    assert kinds == {"envelope", "moved"}
    provider_names = {v.offer for v in ei.value.violations if v.kind == "envelope"}
    assert provider_names == {"/bench/shelf01/bottle01_0004", "/bench/shelf01/bottle01_0005"}
    consumers = {v.consumer for v in ei.value.violations if v.kind == "moved"}
    assert consumers == {"bottle01"}
    assert r.ledger.channels("bench")["approved"] == "v002"


# -- the two-sided contract: props offer what they are ----------------------

def _entity(tmp_path, name, depts=("modelling", "preview", "surfacing")):
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    subs = []
    for dept in depts:
        (d / dept).mkdir(exist_ok=True)
        sub = d / dept / ("%s_%s.usda" % (name, dept))
        sub.write_text('#usda 1.0\n\ndef Xform "root"\n{\n}\n')
        subs.append("%s/%s_%s.usda" % (dept, name, dept))
    (d / ("%s.usda" % name)).write_text(
        "#usda 1.0\n(\n    subLayers = [\n%s    ]\n)\n\ndef Xform \"root\"\n{\n}\n"
        % "".join("        @%s@,\n" % s for s in subs))
    return d


def test_departments_are_derived_from_sublayers(tmp_path):
    from jitsd.extract import departments
    d = _entity(tmp_path, "bottle01", ("modelling", "preview", "surfacing", "rigging"))
    assert departments(str(d / "bottle01.usda")) == [
        "modelling", "preview", "rigging", "surfacing"]


def test_two_sided_contract_binds_both_ways(tmp_path):
    """The prop consumes a mount; the assembly consumes the prop's
    representations. Dropping a department breaks the ASSEMBLY."""
    from jitsd.contracts import extract_text, resolve
    from jitsd.extract import consumer_interface, provider_interface, read_assembly
    from jitsd.reeval import reevaluate

    _entity(tmp_path, "bottle01")
    asm = _assembly(tmp_path)   # places bottle01 + screw01 (flat files)
    ex = read_assembly(str(asm), "bench")

    prov = extract_text(provider_interface(
        ex, represents={"bottle01": ["modelling", "preview", "surfacing"]}))
    full = extract_text(consumer_interface(
        "bottle01", provides=["modelling", "preview", "surfacing"]))
    res = resolve({"bench": prov, "bottle01": full})
    reps = [b for b in res.bindings if b.consumer == "bench"]
    assert len(reps) == 1 and reps[0].providers == ["bottle01/bottle01/represents"]

    # Republish the prop without its preview department.
    dropped = extract_text(consumer_interface(
        "bottle01", provides=["modelling", "surfacing"]))
    re = reevaluate({"bench": prov, "bottle01": full},
                    {"bench": prov, "bottle01": dropped}, {"bottle01"})
    assert not re.ok
    assert all(v.consumer == "bench" for v in re.breaking)
    kinds = {v.kind for v in re.breaking}
    assert kinds <= {"unresolved", "narrowed"} and kinds


def test_into_assets_writes_the_interface_sublayer(tmp_path):
    from jitsd.extract import read_assembly, write_interfaces
    d = _entity(tmp_path, "bottle01")
    _entity(tmp_path, "screw01", ("modelling",))
    asm = tmp_path / "bench_assembly.usda"
    asm.write_text('''#usda 1.0

def Xform "root"
{
    def Xform "shelf01"
    {
        def Xform "bottle01_0001" (
            prepend references = @./bottle01/bottle01.usda@</root>
        )
        {
            double3 xformOp:translate = (1, 2, 3)
        }
    }
}
''')
    ex = read_assembly(str(asm), "bench")
    paths = write_interfaces(ex, str(tmp_path / "out"), represent=True,
                             into_assets={"bottle01": str(d)})
    # The interface lives INSIDE the asset...
    assert paths["bottle01"].endswith("bottle01/interface/bottle01_interface.usda")
    # ...and the entity root now sublayers it, first.
    from pxr import Sdf
    layer = Sdf.Layer.FindOrOpen(str(d / "bottle01.usda"))
    assert list(layer.subLayerPaths)[0] == "interface/bottle01_interface.usda"
    # Idempotent: writing again does not duplicate the entry.
    write_interfaces(ex, str(tmp_path / "out"), represent=True,
                     into_assets={"bottle01": str(d)})
    layer = Sdf.Layer.FindOrOpen(str(d / "bottle01.usda"))
    assert list(layer.subLayerPaths).count("interface/bottle01_interface.usda") == 1


def test_materials_reads_defs_and_prepended_bindings(tmp_path):
    """ALab authors bindings with `prepend`; explicitItems-only readers see an
    empty look. Both definition and binding contribute names."""
    from jitsd.extract import materials
    p = tmp_path / "look.usda"
    p.write_text('''#usda 1.0

def "root" (
    variantSets = "lod"
    variants = {
        string lod = "high"
    }
)
{
    def Scope "mtl"
    {
        def Material "glass_clear"
        {
        }
    }
    variantSet "lod" = {
        "high" {
            def Mesh "geo"
            {
                prepend rel material:binding = </root/mtl/steel_brushed>
            }
        }
    }
}
''')
    assert materials(str(p)) == ["glass_clear", "steel_brushed"]


def test_shading_and_finish_flow_onto_the_represents_offer(tmp_path):
    from jitsd.contracts import extract_text
    from jitsd.extract import consumer_interface
    s = extract_text(consumer_interface(
        "bottle01", provides=["modelling"],
        shading=["usd_full", "usd_preview"], surface_finish="translucent"))
    (offer,) = s.offers
    assert offer.binds["shading"].value == ["usd_full", "usd_preview"]
    assert offer.binds["finish"].value == "translucent"
    assert offer.binds["finish"].kind == "exact"


def test_finish_derived_from_authored_opacity(tmp_path):
    from jitsd.extract import finish
    glass = tmp_path / "glass.usda"
    glass.write_text("""#usda 1.0

def Material "usd_full"
{
    def Shader "s"
    {
        uniform token info:id = "UsdPreviewSurface"
        float inputs:opacity = 0.1
    }
}
""")
    metal = tmp_path / "metal.usda"
    metal.write_text("""#usda 1.0

def Material "usd_full"
{
    def Shader "s"
    {
        uniform token info:id = "UsdPreviewSurface"
        float inputs:roughness = 0.4
    }
}
""")
    assert finish(str(glass)) == "translucent"
    assert finish(str(metal)) is None   # nothing authored: no claim invented


# -- advisory carriers: furniture placements carry the props on them --------

def _carrier_extraction():
    return Extraction(provider="bench", placements=[
        Placement("/root/shelf01/chemistry_bottle01_0001", "shelf01",
                 "chemistry_bottle01_0001", "chemistry_bottle01", (1.0, 0.0, 0.0)),
        Placement("/root/shelf01/furniture_shelving01_0001", "shelf01",
                 "furniture_shelving01_0001", "furniture_shelving01", (0.0, 0.0, 0.0)),
    ])


def test_carrier_rule_emits_advisory_carriers():
    ex = _carrier_extraction()
    text = provider_interface(ex, carrier_rule="group-furniture")
    assert "jitsd:offer:carrier" in text
    assert "furniture_shelving01_0001" in text
    assert 'carrierRule = "group-furniture' in text
    # the furniture offer itself carries no carrier -- a shelf is not its own
    # carrier. "furniture_shelving01_0001" appears twice: once as a carrier
    # target inside the bottle's offer, once as the furniture offer's own
    # name. The second occurrence starts that offer's own block.
    first = text.index("furniture_shelving01_0001")
    second = text.index("furniture_shelving01_0001", first + 1)
    assert "jitsd:offer:carrier" not in text[second:]


def test_no_rule_no_carrier():
    ex = _carrier_extraction()
    assert "jitsd:offer:carrier" not in provider_interface(ex)


def test_carrier_target_path_is_composed_under_the_provider():
    ex = _carrier_extraction()
    text = provider_interface(ex, carrier_rule="group-furniture")
    assert "</bench/shelf01/furniture_shelving01_0001>" in text


def test_load_limit_refuses_carrier_derivation():
    ex = _carrier_extraction()
    with pytest.raises(ValueError, match="physical meaning"):
        provider_interface(ex, carrier_rule="group-furniture",
                           load_limit={"chemistry_bottle01_0001": 5.0})


def test_write_interfaces_passes_carrier_rule_through(tmp_path):
    ex = _carrier_extraction()
    paths = write_interfaces(ex, str(tmp_path / "iface"), carrier_rule="group-furniture")
    text = Path(paths["bench"]).read_text()
    assert "jitsd:offer:carrier" in text


def test_regression_default_anchor_output_unchanged(tmp_path):
    """anchor='asset' is the default and must reproduce exactly today's
    output for a fixture without carriers -- the existing full test suite
    (test_emitted_interfaces_parse_and_bind, test_nudge_moves_only_that_group,
    test_end_to_end_gate_refuses_a_moved_shelf) is the real regression guard;
    this pins the literal text too."""
    ex = read_assembly(str(_assembly(tmp_path)), "bench")
    text = provider_interface(ex, envelope=1.0)
    assert text.startswith('#usda 1.0\n')
    assert 'def Xform "bench" (' in text
    assert '    def Scope "shelf01"\n    {' in text
    assert '        def Xform "bottle01_0004" (' in text
    assert "over " not in text


# -- anchor="root": overs compose onto the entity's real defaultPrim -------

def test_provider_anchor_root_composes_overs_under_root():
    ex = _carrier_extraction()
    text = provider_interface(ex, anchor="root", carrier_rule="group-furniture")
    assert 'defaultPrim = "root"' in text
    assert 'over "root" (' in text
    assert '    over "shelf01"' in text
    assert '        over "chemistry_bottle01_0001" (' in text
    # carrier targets are under /root/..., NOT /<provider>/...
    assert "</root/shelf01/furniture_shelving01_0001>" in text
    assert "/bench/" not in text


def test_consumer_anchor_root_composes_over_under_root():
    text = consumer_interface("bottle01", anchor="root")
    assert 'defaultPrim = "root"' in text
    assert 'over "root" (' in text
    assert 'def Xform "bottle01"' not in text


def test_anchor_root_output_still_parses_with_real_sdf():
    from pxr import Sdf
    ex = _carrier_extraction()
    text = provider_interface(ex, anchor="root", carrier_rule="group-furniture")
    layer = Sdf.Layer.CreateAnonymous(".usda")
    assert layer.ImportFromString(text)
    ctext = consumer_interface("bottle01", anchor="root", provides=["modelling"])
    clayer = Sdf.Layer.CreateAnonymous(".usda")
    assert clayer.ImportFromString(ctext)
