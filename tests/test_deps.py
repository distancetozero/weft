"""Each test asserts an edge USD's own dependency APIs cannot see.

The two that matter most:
  - test_binding_across_files_is_an_edge     (no stock API reports this)
  - test_reverse_dependents                  (USD has no reverse direction at all)
"""

from __future__ import annotations

import textwrap

import pytest

pytest.importorskip("pxr")

from deps import build, discover  # noqa: E402


def _tree(tmp_path, **layers):
    for name, text in layers.items():
        p = tmp_path / ("%s.usda" % name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(textwrap.dedent(text).lstrip())
    return build(discover(str(tmp_path)))


def _names(paths):
    import os
    return sorted(os.path.basename(p) for p in paths)


def _find(g, basename):
    import os
    for i in g.records:
        if os.path.basename(i) == basename:
            return i
    raise AssertionError("no layer named %s" % basename)


# -- the edges stock USD cannot see ----------------------------------------

def test_binding_across_files_is_an_edge(tmp_path):
    """A material binding is a dependency. No stock USD API reports it."""
    g = _tree(
        tmp_path,
        mats='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "Steel"
                {
                }
            }
        ''',
        car='''
            #usda 1.0

            def Xform "Car"
            {
                def Mesh "body"
                {
                    rel material:binding = </Looks/Steel>
                }
            }
        ''',
    )
    car, mats = _find(g, "car.usda"), _find(g, "mats.usda")
    assert mats in g.direct_needs(car), "binding edge was not detected"
    assert car in g.direct_dependents(mats)


def test_reverse_dependents(tmp_path):
    """USD knows what a layer points at. It never knows what points at it."""
    g = _tree(
        tmp_path,
        base='''
            #usda 1.0

            def Xform "Base"
            {
            }
        ''',
        a='''
            #usda 1.0

            def Xform "A" (
                prepend references = @./base.usda@</Base>
            )
            {
            }
        ''',
        b='''
            #usda 1.0

            def Xform "B" (
                prepend references = @./base.usda@</Base>
            )
            {
            }
        ''',
        shot='''
            #usda 1.0

            def Xform "Shot" (
                prepend references = @./a.usda@</A>
            )
            {
            }
        ''',
    )
    base = _find(g, "base.usda")
    assert _names(g.direct_dependents(base)) == ["a.usda", "b.usda"]
    # shot -> a -> base, so shot is a transitive dependent
    assert _names(g.dependents(base)) == ["a.usda", "b.usda", "shot.usda"]


def test_attribute_connection_is_an_edge(tmp_path):
    """Shader networks connect across files by attribute connection."""
    g = _tree(
        tmp_path,
        tex='''
            #usda 1.0

            def Scope "Textures"
            {
                def Shader "Diffuse"
                {
                    token outputs:rgb
                }
            }
        ''',
        shader='''
            #usda 1.0

            def Shader "Surface"
            {
                token inputs:color.connect = </Textures/Diffuse.outputs:rgb>
            }
        ''',
    )
    assert _find(g, "tex.usda") in g.direct_needs(_find(g, "shader.usda"))


def test_inherit_is_an_edge(tmp_path):
    """A class arc that goes missing contributes nothing, silently."""
    g = _tree(
        tmp_path,
        classes='''
            #usda 1.0

            class "_props"
            {
                double size = 1
            }
        ''',
        prop='''
            #usda 1.0

            def Xform "Lamp" (
                inherits = </_props>
            )
            {
            }
        ''',
    )
    assert _find(g, "classes.usda") in g.direct_needs(_find(g, "prop.usda"))


def test_asset_valued_attribute_is_an_edge(tmp_path):
    (tmp_path / "map.usda").write_text("#usda 1.0\n")
    g = _tree(
        tmp_path,
        mat='''
            #usda 1.0

            def Shader "Tex"
            {
                asset inputs:file = @./map.usda@
            }
        ''',
    )
    assert _find(g, "map.usda") in g.direct_needs(_find(g, "mat.usda"))


def test_edges_inside_variants_are_found(tmp_path):
    """A walk that skips variants under-reports, which is how things strand."""
    g = _tree(
        tmp_path,
        damaged='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "Burnt"
                {
                }
            }
        ''',
        car='''
            #usda 1.0

            def Xform "Car" (
                variants = {
                    string state = "clean"
                }
                prepend variantSets = "state"
            )
            {
                variantSet "state" = {
                    "clean" {
                    }
                    "wrecked" {
                        def Mesh "body"
                        {
                            rel material:binding = </Looks/Burnt>
                        }
                    }
                }
            }
        ''',
    )
    assert _find(g, "damaged.usda") in g.direct_needs(_find(g, "car.usda")), \
        "edge inside an unselected variant was missed"


# -- the tool must not cry wolf --------------------------------------------

def test_intra_layer_reference_is_not_a_dependency(tmp_path):
    """Binding to a material in the same file is not an external edge."""
    g = _tree(
        tmp_path,
        solo='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "M"
                {
                }
            }

            def Mesh "geo"
            {
                rel material:binding = </Looks/M>
            }
        ''',
    )
    solo = _find(g, "solo.usda")
    assert g.direct_needs(solo) == set()
    assert g.unresolved == []


def test_override_does_not_define_a_prim(tmp_path):
    """An `over` contributes opinions but is not the home of a prim.

    If overrides counted as definitions, every shot layer would look like the
    owner of every asset it tweaks, and the graph would point backwards.
    """
    g = _tree(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Hero"
            {
            }
        ''',
        shot='''
            #usda 1.0
            (
                subLayers = [@./asset.usda@]
            )

            over "Hero"
            {
                double tweak = 2
            }
        ''',
        other='''
            #usda 1.0

            def Xform "Other"
            {
                rel proxyPrim = </Hero>
            }
        ''',
    )
    # other -> asset (which defines Hero), never other -> shot
    assert _find(g, "asset.usda") in g.direct_needs(_find(g, "other.usda"))
    assert _find(g, "shot.usda") not in g.direct_needs(_find(g, "other.usda"))


# -- closure, orphans, provenance ------------------------------------------

def test_needs_is_transitive(tmp_path):
    g = _tree(
        tmp_path,
        c='#usda 1.0\n\ndef Xform "C"\n{\n}\n',
        b='''
            #usda 1.0

            def Xform "B" (
                prepend references = @./c.usda@</C>
            )
            {
            }
        ''',
        a='''
            #usda 1.0

            def Xform "A" (
                prepend references = @./b.usda@</B>
            )
            {
            }
        ''',
    )
    assert _names(g.needs(_find(g, "a.usda"))) == ["b.usda", "c.usda"]
    assert _names(g.needs(_find(g, "a.usda"), depth=1)) == ["b.usda"]


def test_orphan_edge_is_reported(tmp_path):
    g = _tree(
        tmp_path,
        lonely='''
            #usda 1.0

            def Mesh "geo"
            {
                rel material:binding = </Nowhere/Missing>
            }
        ''',
    )
    assert len(g.unresolved) == 1
    assert g.unresolved[0].target == "/Nowhere/Missing"
    assert g.unresolved[0].kind == "rel"


def test_why_names_the_authored_opinion(tmp_path):
    g = _tree(
        tmp_path,
        mats='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "Steel"
                {
                }
            }
        ''',
        car='''
            #usda 1.0

            def Mesh "body"
            {
                rel material:binding = </Looks/Steel>
            }
        ''',
    )
    edges = g.why(_find(g, "car.usda"), _find(g, "mats.usda"))
    assert len(edges) == 1
    assert edges[0].name == "material:binding"
    assert edges[0].src_prim == "/body"


def test_path_between(tmp_path):
    g = _tree(
        tmp_path,
        c='#usda 1.0\n\ndef Xform "C"\n{\n}\n',
        b='''
            #usda 1.0

            def Xform "B" (
                prepend references = @./c.usda@</C>
            )
            {
            }
        ''',
        a='''
            #usda 1.0

            def Xform "A" (
                prepend references = @./b.usda@</B>
            )
            {
            }
        ''',
    )
    chain = g.path_between(_find(g, "a.usda"), _find(g, "c.usda"))
    assert _names(chain) == ["a.usda", "b.usda", "c.usda"]


# -- cache -----------------------------------------------------------------

def test_cache_reuses_unchanged_and_rewalks_changed(tmp_path):
    from deps import Cache

    (tmp_path / "x.usda").write_text('#usda 1.0\n\ndef Xform "X"\n{\n}\n')
    (tmp_path / "y.usda").write_text('#usda 1.0\n\ndef Xform "Y"\n{\n}\n')
    cache_path = str(tmp_path / "cache.json")
    paths = discover(str(tmp_path))

    c1 = Cache(cache_path)
    build(paths, cache=c1)
    c1.save()
    assert c1.misses == 2 and c1.hits == 0

    c2 = Cache(cache_path)
    build(paths, cache=c2)
    assert c2.hits == 2 and c2.misses == 0

    import os
    import time
    time.sleep(0.01)
    (tmp_path / "y.usda").write_text(
        '#usda 1.0\n\ndef Xform "Y"\n{\n    double extra = 1\n}\n')
    os.utime(tmp_path / "y.usda", None)

    c3 = Cache(cache_path)
    build(paths, cache=c3)
    assert c3.hits == 1 and c3.misses == 1, "only the changed layer should re-walk"


# -- regressions found by running on real published assets ------------------

def test_shared_namespace_does_not_invent_edges(tmp_path):
    """Component assets conventionally all define </World>.

    Found against the ASWF sample assets: six layers defined
    /World/Looks/metal, so resolving that path against a global index made
    bolt.usda and washer.usda depend on each other. They have nothing to do
    with one another.
    """
    g = _tree(
        tmp_path,
        bolt='''
            #usda 1.0

            def Xform "World"
            {
                def Scope "Looks"
                {
                    def Material "metal"
                    {
                    }
                }

                def Mesh "bolt"
                {
                    rel material:binding = </World/Looks/metal>
                }
            }
        ''',
        washer='''
            #usda 1.0

            def Xform "World"
            {
                def Scope "Looks"
                {
                    def Material "metal"
                    {
                    }
                }

                def Mesh "washer"
                {
                    rel material:binding = </World/Looks/metal>
                }
            }
        ''',
    )
    bolt, washer = _find(g, "bolt.usda"), _find(g, "washer.usda")
    assert g.direct_needs(bolt) == set(), "invented an edge to a same-named prim"
    assert g.direct_needs(washer) == set()
    assert g.unresolved == []


def test_ambiguity_is_reported_not_guessed(tmp_path):
    """When several unrelated layers could satisfy an edge, say so."""
    g = _tree(
        tmp_path,
        libA='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "metal"
                {
                }
            }
        ''',
        libB='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "metal"
                {
                }
            }
        ''',
        user='''
            #usda 1.0

            def Mesh "geo"
            {
                rel material:binding = </Looks/metal>
            }
        ''',
    )
    user = _find(g, "user.usda")
    assert g.direct_needs(user) == set(), "guessed between two candidates"
    assert len(g.ambiguous) == 1
    src, target, candidates = g.ambiguous[0]
    assert target == "/Looks/metal"
    assert len(candidates) == 2


def test_in_context_candidate_wins(tmp_path):
    """A layer this one actually composes beats an unrelated same-named prim."""
    g = _tree(
        tmp_path,
        mats='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "metal"
                {
                }
            }
        ''',
        unrelated='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "metal"
                {
                }
            }
        ''',
        car='''
            #usda 1.0
            (
                subLayers = [@./mats.usda@]
            )

            def Mesh "body"
            {
                rel material:binding = </Looks/metal>
            }
        ''',
    )
    car = _find(g, "car.usda")
    assert g.direct_needs(car) == {_find(g, "mats.usda")}
    assert _find(g, "unrelated.usda") not in g.direct_needs(car)


def test_one_bad_layer_does_not_abort_the_walk(tmp_path):
    """Found against the ASWF corpus, which ships deliberately-invalid fixtures.

    Any real repository contains at least one file that does not parse -- a bad
    export, a partial write, a test fixture. A dependency tool that dies on the
    first one is a tool nobody can run on their actual assets.
    """
    (tmp_path / "broken.usda").write_text(
        "#usda 1.0\n(\n    framesPerSecond = -1\n)\n")
    g = _tree(
        tmp_path,
        good='''
            #usda 1.0

            def Xform "Fine"
            {
            }
        ''',
    )
    assert _find(g, "good.usda") in g.records
    assert any(p.endswith("broken.usda") for p in g.unreadable)
