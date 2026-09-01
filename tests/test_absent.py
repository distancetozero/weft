"""Each test reproduces a silence USD ships with, and asserts we break it.

The false-positive tests matter as much as the detections: a tool that flags
legitimate sparse overrides is worse than no tool, because sparse overrides are
how USD pipelines are supposed to work.
"""

from __future__ import annotations

import textwrap

import pytest

pytest.importorskip("pxr")

from pxr import Usd  # noqa: E402

from absent import DEAD, MOVED, UNKNOWN, scan  # noqa: E402


def _stage(tmp_path, **layers):
    """Write .usda files and open the one named 'root'."""
    for name, text in layers.items():
        (tmp_path / ("%s.usda" % name)).write_text(textwrap.dedent(text).lstrip())
    return Usd.Stage.Open(str(tmp_path / "root.usda"))


def _kinds(report):
    return sorted(f.kind for f in report.findings)


# -- the tool must stay quiet on healthy scenes ----------------------------

def test_legitimate_sparse_override_is_not_reported(tmp_path):
    """The whole reason USD cannot do this itself. Get it right or go home."""
    stage = _stage(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Char"
            {
                def Xform "Hat"
                {
                    double size = 1
                }
            }
        ''',
        root='''
            #usda 1.0
            (
                subLayers = [@./asset.usda@]
            )

            over "Char"
            {
                over "Hat"
                {
                    double size = 2
                }
            }
        ''',
    )
    assert scan(stage).findings == []


def test_clean_stage_with_bindings_and_targets_is_clean(tmp_path):
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "M"
                {
                }
            }

            def Xform "Geo"
            {
                rel material:binding = </Looks/M>
                rel proxyPrim = </Geo/Proxy>

                def Xform "Proxy"
                {
                }
            }
        ''',
    )
    assert scan(stage).findings == []


# -- the silences ----------------------------------------------------------

def test_stale_override_after_rename(tmp_path):
    """Asset renamed Hat -> Cap. The override stays, composes to nothing."""
    stage = _stage(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Char"
            {
                def Xform "Cap"
                {
                }
            }
        ''',
        root='''
            #usda 1.0
            (
                subLayers = [@./asset.usda@]
            )

            over "Char"
            {
                over "Hat"
                {
                    token visibility = "invisible"
                }
            }
        ''',
    )
    report = scan(stage)
    assert "stale-override" in _kinds(report)
    finding = next(f for f in report.findings if f.kind == "stale-override")
    assert finding.path == "/Char/Hat"
    # Nothing recorded what it was authored against, so we cannot say why.
    assert finding.verdict == UNKNOWN


def test_dangling_relationship_target(tmp_path):
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Xform "Geo"
            {
                rel proxyPrim = </Nope/Nothing>
            }
        ''',
    )
    assert "dangling-target" in _kinds(scan(stage))


def test_binding_to_deactivated_material(tmp_path):
    """ComputeBoundMaterial() hands back a valid material wrapping a dead prim."""
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Scope "Looks"
            {
                def Material "M" (
                    active = false
                )
                {
                }
            }

            def Xform "Geo"
            {
                rel material:binding = </Looks/M>
            }
        ''',
    )
    report = scan(stage)
    assert "binding-deactivated" in _kinds(report)
    assert all(f.verdict == DEAD for f in report.findings
               if f.kind == "binding-deactivated")


def test_target_deactivated_still_resolves(tmp_path):
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Xform "Hidden" (
                active = false
            )
            {
            }

            def Xform "Geo"
            {
                rel proxyPrim = </Hidden>
            }
        ''',
    )
    assert "target-deactivated" in _kinds(scan(stage))


def test_empty_collection(tmp_path):
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Xform "Lights" (
                prepend apiSchemas = ["CollectionAPI:lit"]
            )
            {
                rel collection:lit:includes = </Gone/Away>
            }
        ''',
    )
    assert "empty-collection" in _kinds(scan(stage))


def test_override_under_instanceable_is_discarded(tmp_path):
    stage = _stage(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Proto"
            {
                def Xform "Body"
                {
                    double size = 1
                }
            }
        ''',
        base='''
            #usda 1.0

            def Xform "A" (
                instanceable = true
                prepend references = @./asset.usda@</Proto>
            )
            {
            }
        ''',
        root='''
            #usda 1.0
            (
                subLayers = [@./base.usda@]
            )

            over "A"
            {
                over "Body"
                {
                    double size = 99
                }
            }
        ''',
    )
    assert "override-in-instance" in _kinds(scan(stage))


# -- anchors: the reason to carry a name separate from the hierarchy -------

def test_anchor_turns_unknown_into_moved(tmp_path):
    """The same broken override, with the anchor recorded, becomes actionable.

    Without the anchor the tool can only say "this refers to nothing". With it,
    the tool says the thing moved, and where it went.
    """
    stage = _stage(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Char"
            {
                def Xform "Cap" (
                    customData = {
                        dictionary absent = {
                            string id = "hat-7f2a"
                        }
                    }
                )
                {
                }
            }
        ''',
        root='''
            #usda 1.0
            (
                subLayers = [@./asset.usda@]
            )

            over "Char"
            {
                over "Hat" (
                    customData = {
                        dictionary absent = {
                            string authoredAgainst = "hat-7f2a"
                        }
                    }
                )
                {
                    token visibility = "invisible"
                }
            }
        ''',
    )
    report = scan(stage)
    assert report.anchors_found == 1
    finding = next(f for f in report.findings if f.kind == "stale-override")
    assert finding.verdict == MOVED
    assert finding.moved_to == "/Char/Cap"
    assert report.dead == []


def test_anchor_absent_means_genuinely_dead(tmp_path):
    """Anchor recorded, but no prim carries it any more -- the thing is gone."""
    stage = _stage(
        tmp_path,
        asset='''
            #usda 1.0

            def Xform "Char"
            {
            }
        ''',
        root='''
            #usda 1.0
            (
                subLayers = [@./asset.usda@]
            )

            over "Char"
            {
                over "Hat" (
                    customData = {
                        dictionary absent = {
                            string authoredAgainst = "hat-7f2a"
                        }
                    }
                )
                {
                    token visibility = "invisible"
                }
            }
        ''',
    )
    report = scan(stage)
    finding = next(f for f in report.findings if f.kind == "stale-override")
    assert finding.verdict == DEAD
    assert finding.moved_to is None


# -- regression found by running on the ASWF encapsulation test suite -------

def test_targets_stripped_by_encapsulation(tmp_path):
    """A binding whose target is out of the reference's scope is DISCARDED.

    The relationship survives with an empty target list and the mesh renders
    unshaded. There is no dangling target to find, which is why a check that
    only looks for unresolvable targets misses it entirely. USD warns at
    composition, in a log nobody reads.
    """
    stage = _stage(
        tmp_path,
        washer='''
            #usda 1.0
            (
                defaultPrim = "World"
            )

            def Xform "World"
            {
                def Scope "Looks"
                {
                    def Material "metal"
                    {
                    }
                }

                def Scope "Geometry"
                {
                    def Mesh "washer"
                    {
                        rel material:binding = </World/Looks/metal>
                    }
                }
            }
        ''',
        root='''
            #usda 1.0

            def Xform "World"
            {
                def "washer" (
                    prepend references = @./washer.usda@</World/Geometry/washer>
                )
                {
                }
            }
        ''',
    )
    report = scan(stage)
    kinds = _kinds(report)
    assert "targets-stripped" in kinds
    f = next(f for f in report.findings if f.kind == "targets-stripped")
    assert f.verdict == DEAD
    assert "/World/Looks/metal" in f.detail


def test_relationship_with_no_targets_authored_is_not_a_finding(tmp_path):
    """An empty relationship that never had targets is normal, not a break."""
    stage = _stage(
        tmp_path,
        root='''
            #usda 1.0

            def Mesh "geo"
            {
                rel material:binding
            }
        ''',
    )
    assert "targets-stripped" not in _kinds(scan(stage))
