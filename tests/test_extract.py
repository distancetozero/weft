"""Extracting a contract surface from an existing assembly."""

from __future__ import annotations

import textwrap

import pytest

pytest.importorskip("pxr")

from jitsd.contracts import extract_text, resolve  # noqa: E402
from jitsd.extract import (  # noqa: E402
    consumer_interface, provider_interface, read_assembly, write_interfaces,
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
