import pytest

pxr = pytest.importorskip("pxr")

from weft.pull import edge_kind_of, pull, who

CTX = """#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Scope "Looks"
    {
        def Material "glass"
        {
        }
        def Material "steel"
        {
        }
    }
    def Xform "shelf01"
    {
        def Xform "bottle_0001"
        {
            rel material:binding = </root/Looks/glass>
            rel custom:pairedWith = </root/shelf01/bottle_0002>
        }
        def Xform "bottle_0002"
        {
            rel material:binding = </root/Looks/steel>
        }
        def Xform "crate_0001"
        {
        }
    }
}
"""


@pytest.fixture
def ctx(tmp_path):
    p = tmp_path / "ctx.usda"
    p.write_text(CTX)
    return str(p)


def test_edge_kind_is_namespaced_name():
    assert edge_kind_of("material:binding") == "material:binding"
    assert edge_kind_of("custom:pairedWith") == "custom:pairedWith"
    assert edge_kind_of("proxyPrim") == "usd:rel"


def test_seed_only_pull_declares_boundary(ctx):
    p = pull(ctx, ["bottle_0001"], follow=[])
    paths = [m.path for m in p.members]
    assert paths == ["/root/shelf01/bottle_0001"]
    kinds = {(b.kind, b.reason) for b in p.boundary}
    assert ("material:binding", "not followed") in kinds
    assert ("custom:pairedWith", "not followed") in kinds


def test_followed_kind_pulls_target_with_provenance(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["material:binding"])
    m = {m.path: m for m in p.members}
    assert "/root/Looks/glass" in m
    assert m["/root/Looks/glass"].via_kind == "material:binding"
    assert m["/root/Looks/glass"].from_member == "/root/shelf01/bottle_0001"
    # steel was NOT pulled: bottle_0002 is not a member
    assert "/root/Looks/steel" not in m


def test_team_kind_followed_by_its_own_name(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["custom:pairedWith"])
    assert "/root/shelf01/bottle_0002" in [m.path for m in p.members]


def test_spine_not_canopy(ctx):
    p = pull(ctx, ["bottle_0001"], follow=["material:binding"])
    paths = [m.path for m in p.members]
    assert "/root/shelf01/crate_0001" not in paths      # sibling absent
    assert "/root/shelf01/bottle_0002" not in paths


def test_reverse_follow(ctx):
    p = pull(ctx, ["bottle_0002"], follow=["up:custom:pairedWith"])
    assert "/root/shelf01/bottle_0001" in [m.path for m in p.members]
    assert any("component closure" in d for d in p.declarations)


def test_depth_cut_distinct_from_not_followed(tmp_path):
    chain = ["#usda 1.0", "(", '    defaultPrim = "root"', ")", "",
             'def Xform "root"', "{"]
    for i in range(4):
        chain += ['    def Xform "n%d"' % i, "    {",
                  "        rel c:next = </root/n%d>" % (i + 1)]
        if i == 2:
            # An up:-only kind edge authored on the final frontier prim
            # (n2): the sweep only examines forward edges, so this must
            # land as "not followed", never "beyond depth N".
            chain += ["        rel special:only = </root/n4>"]
        chain += ["    }"]
    chain += ['    def Xform "n4"', "    {", "    }", "}", ""]
    f = tmp_path / "chain.usda"
    f.write_text("\n".join(chain))
    p = pull(str(f), ["n0"], follow=["c:next", "up:special:only"], depth=2)
    reasons = {b.reason for b in p.boundary}
    assert "beyond depth 2" in reasons
    kinds_reasons = {(b.kind, b.reason) for b in p.boundary}
    assert ("special:only", "not followed") in kinds_reasons


def test_who_reports_incoming_edges(ctx):
    hits = who(ctx, ["bottle_0002"])
    assert ("/root/shelf01/bottle_0001", "custom:pairedWith",
            "/root/shelf01/bottle_0002") in hits


def test_who_multi_hop_reverse_expansion(tmp_path):
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
    def Xform "b"
    {
        rel c:next = </root/c>
    }
    def Xform "c"
    {
    }
}
""")
    hits2 = who(str(f), ["name:c"], depth=2)
    assert ("/root/b", "c:next", "/root/c") in hits2
    assert ("/root/a", "c:next", "/root/b") in hits2

    hits1 = who(str(f), ["name:c"], depth=1)
    assert ("/root/b", "c:next", "/root/c") in hits1
    assert ("/root/a", "c:next", "/root/b") not in hits1


def test_per_kind_terms_merge_both_directions(tmp_path):
    f = tmp_path / "pair.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "A"
    {
        rel custom:pairedWith = </root/B>
    }
    def Xform "B"
    {
    }
    def Xform "C"
    {
        rel custom:pairedWith = </root/A>
    }
}
""")
    p = pull(str(f), ["name:A"],
             follow=["custom:pairedWith", "up:custom:pairedWith"])
    paths = [m.path for m in p.members]
    assert "/root/B" in paths   # forward: A -> B
    assert "/root/C" in paths   # reverse: C -> A


def test_contract_edge_exposes_carrier_targets(tmp_path):
    f = tmp_path / "c.usda"
    f.write_text("""#usda 1.0
(
    defaultPrim = "root"
)

def Xform "root"
{
    def Xform "bottle"
    {
        uniform token weft:offer:contract = "Mount@1"
        rel weft:offer:carrier = </root/shelf>
    }
    def Xform "shelf"
    {
    }
}
""")
    p = pull(str(f), ["name:bottle"], follow=["Mount"])
    assert "/root/shelf" in [m.path for m in p.members]
    m = {m.path: m for m in p.members}
    assert m["/root/shelf"].via_kind == "Mount"
