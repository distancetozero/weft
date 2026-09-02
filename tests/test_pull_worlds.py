import pytest

pxr = pytest.importorskip("pxr")

from jitsd.pull import pull

VARIANT_CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "hero"
        {
        }
        def Material "cheap"
        {
        }
    }
    def Xform "prop" (
        variants = { string lod = "proxy" }
        prepend variantSets = "lod"
    )
    {
        variantSet "lod" = {
            "full" {
                rel material:binding = </root/Looks/hero>
            }
            "proxy" {
                rel material:binding = </root/Looks/cheap>
            }
        }
    }
}
"""


def test_unselected_variant_edges_declared_not_followed(tmp_path):
    f = tmp_path / "v.usda"
    f.write_text(VARIANT_CTX)
    p = pull(str(f), ["prop"], follow=["material:binding"])
    paths = [m.path for m in p.members]
    assert "/root/Looks/cheap" in paths          # selected world followed
    assert "/root/Looks/hero" not in paths       # unselected world NOT pulled
    variant_kinds = [b for b in p.boundary if b.kind.startswith("usd:variant(")]
    assert any(b.kind == "usd:variant(lod=full)" for b in variant_kinds)
    assert any(s == "/root/prop lod=proxy" for s in p.variant_selections)


def test_unselected_variant_target_pulled_later_not_boundary(tmp_path):
    """R13: a target that only becomes a member on a LATER BFS wave (via a
    different member entirely) must not carry a stale usd:variant(...)
    boundary entry staged when the variant-holding prim was first visited."""
    f = tmp_path / "relay.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "hero"
        {
        }
        def Material "cheap"
        {
        }
    }
    def Xform "prop" (
        variants = { string lod = "proxy" }
        prepend variantSets = "lod"
    )
    {
        rel custom:next = </root/relay>
        variantSet "lod" = {
            "full" {
                rel material:binding = </root/Looks/hero>
            }
            "proxy" {
                rel material:binding = </root/Looks/cheap>
            }
        }
    }
    def Xform "relay"
    {
        rel backup:material = </root/Looks/hero>
    }
}
""")
    p = pull(str(f), ["prop"],
             follow=["material:binding", "custom:next", "backup:material"])
    paths = [m.path for m in p.members]
    assert "/root/Looks/hero" in paths            # reached via relay, later wave
    assert not any(b.kind.startswith("usd:variant(") and b.target == "/root/Looks/hero"
                   for b in p.boundary)


def test_final_wave_member_variant_recorded(tmp_path):
    """R14: a member admitted only on the final BFS wave (depth exhausted
    right as it's discovered) still gets its variant selection recorded."""
    f = tmp_path / "chain.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "a"
    {
        rel c:next = </root/b>
    }
    def Xform "b" (
        variants = { string mode = "on" }
        prepend variantSets = "mode"
    )
    {
        variantSet "mode" = {
            "on" {
            }
            "off" {
            }
        }
    }
}
""")
    p = pull(str(f), ["name:a"], follow=["c:next"], depth=1)
    assert "/root/b" in [m.path for m in p.members]
    assert "/root/b mode=on" in p.variant_selections


def test_payload_interior_member(tmp_path):
    (tmp_path / "inner.usda").write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "mtl"
    {
        def Material "usd_full"
        {
        }
    }
}
""")
    (tmp_path / "outer.usda").write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "asset" (
        payload = @./inner.usda@
    )
    {
    }
}
""")
    p = pull(str(tmp_path / "outer.usda"), ["path:/root/asset/mtl/usd_full"])
    assert [m.path for m in p.members] == ["/root/asset/mtl/usd_full"]
    assert any("payload" in d for d in p.declarations)
    assert any(l[0].endswith("inner.usda") for l in p.layers)
    # R15: the invalid-but-confirmed member's nearest valid ancestor
    # (/root/asset, defined in outer.usda) also lands in p.layers.
    assert any(l[0].endswith("outer.usda") for l in p.layers)
