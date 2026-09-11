"""The weft__kinds loader (2026-09-04-weft-kinds-loader.md): one declarative
block -> one RelationshipKind carrying the extractor, omission class, and lens
display. Parse/load/validate tests are pxr-free (like test_query); the
pull/graph/CLI wiring tests need a real stage and importorskip pxr locally."""

import pytest

from weft import kinds as kinds_mod
from weft import registry
from weft.kinds import (
    BUILTIN_DERIVERS,
    DeclaredReadKind,
    discover,
    emit_kinds_document,
    load_kinds,
    parse_kinds,
)
from weft.registry import Extractor, MEANING_CHANGING, omission_class
from weft.relkinds import REGISTRY, RelationshipKind

POWERED_BY = {
    "kind": "PoweredBy",
    "label": "Power",
    "color": "#e0b050",
    "structure": "edge",
    "omission": "meaning-changing",
    "population": {"read": {"attr": "myteam:poweredBy", "target": "primPath"}},
}


@pytest.fixture(autouse=True)
def _clean_loader_state():
    """load_kinds registers omission classes globally and discover caches per
    layer; both are cleared around every test so nothing leaks."""
    registry.DECLARED_OMISSIONS.clear()
    kinds_mod._DISCOVER_CACHE.clear()
    yield
    registry.DECLARED_OMISSIONS.clear()
    kinds_mod._DISCOVER_CACHE.clear()


# -- parse (pxr-free) --------------------------------------------------------


def test_parse_kinds_roundtrips_emitted_document():
    doc = emit_kinds_document([POWERED_BY], "team.usda")
    assert parse_kinds(doc) == [POWERED_BY]


def test_parse_kinds_reads_triple_quoted_block():
    # The spec's own example spelling.
    text = '''#usda 1.0
(
    customLayerData = {
        string weft__kinds = """[
          {
            "kind":       "PoweredBy",
            "label":      "Power",
            "population": { "read": { "attr": "myteam:poweredBy", "target": "primPath" } }
          }
        ]"""
    }
)
'''
    decls = parse_kinds(text)
    assert len(decls) == 1 and decls[0]["kind"] == "PoweredBy"


def test_parse_kinds_raises_on_absent_or_malformed_block():
    with pytest.raises(ValueError, match="no weft__kinds block"):
        parse_kinds("#usda 1.0\n")
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_kinds('string weft__kinds = """[oops"""')
    with pytest.raises(ValueError, match="array of objects"):
        parse_kinds('string weft__kinds = """{"kind": "X"}"""')


# -- load + validate (pxr-free) ----------------------------------------------


def test_load_read_kind_carries_all_four_touchpoints():
    (k,) = load_kinds([POWERED_BY])
    assert isinstance(k, DeclaredReadKind)
    assert k.type_id == "PoweredBy"                              # lens/edge id
    assert k.extractor == Extractor("myteam:poweredBy", "PoweredBy", "primPath")
    assert k.display == {"label": "Power", "color": "#e0b050"}   # lens display
    assert k.facet is False
    # loading registered the omission class with the registry
    assert omission_class("PoweredBy") == MEANING_CHANGING


def test_load_defaults_label_omission_structure():
    (k,) = load_kinds([{"kind": "Feeds",
                        "population": {"read": {"attr": "x:feeds"}}}])
    assert k.display["label"] == "Feeds"
    assert k.omission == "inert" and omission_class("Feeds") == "inert"
    assert k.facet is False


def test_load_rejects_unknown_population_mode():
    with pytest.raises(ValueError, match="unknown population mode"):
        load_kinds([{"kind": "X", "population": {"synthesize": {}}}])


def test_load_rejects_duplicate_kind():
    a = {"kind": "X", "population": {"read": {"attr": "t:a"}}}
    with pytest.raises(ValueError, match="duplicate kind"):
        load_kinds([a, dict(a)])


def test_load_rejects_kind_shadowing_a_builtin():
    for taken in ("usd:arc", "Mount"):
        with pytest.raises(ValueError, match="shadows a built-in"):
            load_kinds([{"kind": taken,
                         "population": {"read": {"attr": "t:a"}}}])


def test_load_rejects_bad_omission_and_missing_pieces():
    with pytest.raises(ValueError, match="omission must be"):
        load_kinds([{"kind": "X", "omission": "sometimes",
                     "population": {"read": {"attr": "t:a"}}}])
    with pytest.raises(ValueError, match="needs a string 'kind'"):
        load_kinds([{"population": {"read": {"attr": "t:a"}}}])
    with pytest.raises(ValueError, match="read mode needs an 'attr'"):
        load_kinds([{"kind": "X", "population": {"read": {}}}])
    with pytest.raises(ValueError, match="exactly one of"):
        load_kinds([{"kind": "X"}])
    # a failing batch registers nothing (validation is all-or-nothing)
    assert "X" not in registry.DECLARED_OMISSIONS


def test_derive_dispatches_to_named_builtin_subclass():
    class FakeDeriver(RelationshipKind):
        pass

    BUILTIN_DERIVERS["material-binding"] = FakeDeriver
    try:
        (k,) = load_kinds([{
            "kind": "BoundTo", "structure": "facet",
            "omission": "meaning-changing",
            "population": {"derive": {"builtin": "material-binding"}}}])
        assert isinstance(k, FakeDeriver)
        assert k.type_id == "BoundTo" and k.facet is True
        assert omission_class("BoundTo") == MEANING_CHANGING
    finally:
        del BUILTIN_DERIVERS["material-binding"]


def test_derive_unknown_builtin_raises_with_roster():
    with pytest.raises(ValueError, match="no built-in deriver named"):
        load_kinds([{"kind": "X",
                     "population": {"derive": {"builtin": "nope"}}}])
    with pytest.raises(ValueError, match="no built-in miner named"):
        load_kinds([{"kind": "X",
                     "population": {"mine": {"builtin": "nope"}}}])


def test_declared_omission_cannot_soften_the_soundness_floor():
    load_kinds([{"kind": "physics:custom", "omission": "inert",
                 "population": {"read": {"attr": "t:a"}}}])
    assert omission_class("physics:custom") == MEANING_CHANGING


# -- pull / graph / CLI wiring (needs pxr) -----------------------------------

CTX = """#usda 1.0
(
    defaultPrim = "root"
    customLayerData = {
        string weft__kinds = \"\"\"[
          {
            "kind":       "PoweredBy",
            "label":      "Power",
            "color":      "#e0b050",
            "omission":   "meaning-changing",
            "population": { "read": { "attr": "myteam:poweredBy", "target": "primPath" } }
          }
        ]\"\"\"
    }
)

def Xform "root"
{
    def Xform "set_01"
    {
        def Xform "device_0001"
        {
            string myteam:poweredBy = "/root/set_01/battery_0001"
        }
        def Xform "battery_0001"
        {
        }
    }
}
"""


def _write_ctx(tmp_path):
    f = tmp_path / "ctx.usda"
    f.write_text(CTX)
    return f


def test_pull_follows_a_declared_read_kind(tmp_path):
    pytest.importorskip("pxr")
    from weft.pull import pull
    f = _write_ctx(tmp_path)
    (k,) = load_kinds(parse_kinds(f.read_text()))
    p = pull(str(f), ["name:device_0001"], follow=["PoweredBy"],
             extractors=[k.extractor])
    assert "/root/set_01/battery_0001" in [m.path for m in p.members]


def test_cut_declared_edge_is_a_meaning_changing_boundary(tmp_path):
    pytest.importorskip("pxr")
    from weft.pull import pull
    f = _write_ctx(tmp_path)
    (k,) = load_kinds(parse_kinds(f.read_text()))
    p = pull(str(f), ["name:device_0001"], extractors=[k.extractor])
    cut = [b for b in p.boundary if b.kind == "PoweredBy"]
    assert cut and cut[0].target == "/root/set_01/battery_0001"
    assert cut[0].omission == MEANING_CHANGING


def test_build_graph_gains_the_declared_lens_automatically(tmp_path):
    pytest.importorskip("pxr")
    from pxr import Usd
    from weft.threadgraph import build_graph
    f = _write_ctx(tmp_path)
    g = build_graph(Usd.Stage.Open(str(f)))
    assert "PoweredBy" in g["kinds"]
    assert {"source": "/root/set_01/device_0001",
            "target": "/root/set_01/battery_0001",
            "kind": "PoweredBy"} in g["edges"]


def test_discover_without_declarations_is_exactly_the_builtins(tmp_path):
    pytest.importorskip("pxr")
    from pxr import Usd
    f = tmp_path / "plain.usda"
    f.write_text('#usda 1.0\n(\n    defaultPrim = "root"\n)\n\n'
                 'def Xform "root"\n{\n}\n')
    assert discover(Usd.Stage.Open(str(f))) == REGISTRY
    assert discover(None) == REGISTRY


def test_discover_reads_the_weft_sidecar(tmp_path):
    pytest.importorskip("pxr")
    from pxr import Usd
    f = tmp_path / "scene.usda"
    f.write_text('#usda 1.0\n(\n    defaultPrim = "root"\n)\n\n'
                 'def Xform "root"\n{\n}\n')
    (tmp_path / "scene.weft.usda").write_text(
        emit_kinds_document([POWERED_BY], "scene.weft.usda"))
    found = discover(Usd.Stage.Open(str(f)))
    assert [k.type_id for k in found[len(REGISTRY):]] == ["PoweredBy"]


def test_cli_pull_kinds_end_to_end(tmp_path, capsys):
    pytest.importorskip("pxr")
    from weft.cli import main
    f = _write_ctx(tmp_path)
    sidecar = tmp_path / "team.usda"
    sidecar.write_text(emit_kinds_document([POWERED_BY], "team.usda"))
    rc = main(["pull", "name:device_0001", "--context", str(f),
               "--follow", "PoweredBy", "--kinds", str(sidecar)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "/root/set_01/battery_0001" in out
    assert "PoweredBy <- /root/set_01/device_0001" in out
    # without follow: the declared edge is a declared meaning-changing cut
    rc = main(["pull", "name:device_0001", "--context", str(f),
               "--kinds", str(sidecar)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[meaning-changing]" in out


def test_cli_pull_kinds_rejects_a_malformed_sidecar(tmp_path, capsys):
    pytest.importorskip("pxr")
    from weft.cli import main
    f = _write_ctx(tmp_path)
    sidecar = tmp_path / "bad.usda"
    sidecar.write_text('#usda 1.0\n(\n    customLayerData = {\n'
                       '        string weft__kinds = """[{"kind": "X"}]"""\n'
                       '    }\n)\n')
    rc = main(["pull", "name:device_0001", "--context", str(f),
               "--kinds", str(sidecar)])
    assert rc == 1
    err = capsys.readouterr().err
    assert "population must be exactly one of" in err
    assert "Traceback" not in err
