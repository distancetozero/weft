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
