"""Pulling one thread: closure by relationship kind, and rule sets as content.

The premise: pull on threads explicitly, with rules, without loading the
whole thing. On ALab, seeding one bottle pulled all 165 assets, because the
bottle needs the bench and the bench's assembly references every prop --
correct, and useless. `follow` makes which threads to pull a choice, and a
rule set makes that choice a team's shareable, versioned artifact.
"""

from __future__ import annotations

import textwrap

import pytest

from jitsd.ledger import Repo
from jitsd.slice import (
    RuleSet, SliceSpec, emit_rules_document, load_rules, read_rules,
    resolve_slice, save_rules,
)


def _repo(tmp_path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.init()
    return r


def _usda(tmp_path, name, text):
    p = tmp_path / ("%s.usda" % name)
    p.write_text(textwrap.dedent(text).lstrip())
    return p


# -- a world with two kinds of thread from one asset -----------------------

def _two_threads(tmp_path):
    """bottle --Mount--> bench   and   bottle --usd:binding--> mats.

    Both are real dependencies. They are different threads.
    """
    r = _repo(tmp_path)
    bench_iface = _usda(tmp_path, "bench.iface", '''
        #usda 1.0

        def Xform "bench" (
            prepend apiSchemas = ["JitsdOfferAPI"]
        )
        {
            uniform token jitsd:offer:contract = "Mount@1"
            uniform token jitsd:mount:role = "bottle"
            double3 xformOp:translate = (0, 143, 0)
        }
    ''')
    bottle_iface = _usda(tmp_path, "bottle.iface", '''
        #usda 1.0

        def Xform "bottle" (
            prepend apiSchemas = ["JitsdRequireAPI:mount"]
        )
        {
            uniform token jitsd:require:mount:contract = "Mount@1"
            uniform token jitsd:require:mount:role = "bottle"
            uniform token jitsd:require:mount:cardinality = "many"
        }
    ''')
    # Real USDA is strict: nested defs need their own lines and braces.
    mats = _usda(tmp_path, "mats", '''
        #usda 1.0

        def Scope "Looks"
        {
            def Material "Glass"
            {
            }
        }
    ''')
    bottle = _usda(tmp_path, "bottle", '''
        #usda 1.0

        def Mesh "bottle"
        {
            rel material:binding = </Looks/Glass>
        }
    ''')
    bench = _usda(tmp_path, "bench", '''
        #usda 1.0

        def Xform "bench"
        {
        }
    ''')
    r.save("bench", bench, "t", interface=bench_iface)
    r.save("mats", mats, "t")
    r.save("bottle", bottle, "t", interface=bottle_iface)
    return r


pxr = pytest.importorskip("pxr")


def test_unfiltered_closure_pulls_every_thread(tmp_path):
    r = _two_threads(tmp_path)
    res = resolve_slice(r, SliceSpec(seeds=["bottle"], channel="wip"))
    assert {m.asset for m in res.members} == {"bottle", "bench", "mats"}


def test_follow_a_contract_pulls_only_that_thread(tmp_path):
    r = _two_threads(tmp_path)
    res = resolve_slice(r, SliceSpec(seeds=["bottle"], channel="wip", follow=["Mount"]))
    assert {m.asset for m in res.members} == {"bottle", "bench"}
    # The other thread is declared at the boundary, never silently dropped.
    assert any(b.asset == "mats" and "usd:binding not followed" in b.why_excluded
               for b in res.boundary)


def test_follow_a_usd_kind_pulls_only_that_thread(tmp_path):
    r = _two_threads(tmp_path)
    res = resolve_slice(r, SliceSpec(seeds=["bottle"], channel="wip",
                                     follow=["usd:binding"]))
    assert {m.asset for m in res.members} == {"bottle", "mats"}
    assert any(b.asset == "bench" and "Mount not followed" in b.why_excluded
               for b in res.boundary)


def test_provenance_names_the_kind(tmp_path):
    r = _two_threads(tmp_path)
    res = resolve_slice(r, SliceSpec(seeds=["bottle"], channel="wip"))
    by = {m.asset: m for m in res.members}
    assert "Mount" in by["bench"].provenance.detail
    assert "usd:binding" in by["mats"].provenance.detail


# -- rule sets as content ----------------------------------------------------

def test_rules_round_trip_through_a_document():
    rs = RuleSet(closure=["needs"], follow=["Mount", "usd:binding"], depth=2,
                 view=["position", "material"], context="lighting", label="lighting",
                 author="dana", note="what lighting pulls")
    text = emit_rules_document(rs, "lighting.rules")
    back = read_rules(text)
    assert back == rs


def test_rules_are_an_asset_revision_and_apply_to_a_slice(tmp_path):
    r = _two_threads(tmp_path)
    rs = RuleSet(follow=["Mount"], depth=1, view=["position"], label="lookdev")
    rev = save_rules(r, "lookdev.rules", rs, "dana", "only mounts")
    assert rev == "v001"
    assert r.ledger.read_revision("lookdev.rules", rev).message == "only mounts"

    loaded, applied = load_rules(r, "lookdev.rules")
    assert loaded.follow == ["Mount"] and applied == "lookdev.rules@v001"

    spec = SliceSpec(seeds=["bottle"], channel="wip")
    loaded.apply(spec, overrides={"closure": None, "follow": None, "depth": None,
                                  "include_optional": None, "view": None, "context": None})
    spec.rules = applied
    res = resolve_slice(r, spec)
    assert {m.asset for m in res.members} == {"bottle", "bench"}
    assert res.spec.rules == "lookdev.rules@v001"


def test_rules_fill_only_what_was_not_given():
    """apply() leaves a field alone when the caller gave it explicitly."""
    rs = RuleSet(follow=["Mount"], depth=1, context="lighting")
    spec = SliceSpec(seeds=["x"])
    given = {"follow": ["usd:binding"], "depth": None, "closure": None,
             "include_optional": None, "view": None, "context": None}
    rs.apply(spec, given)
    assert spec.depth == 1                 # not given: filled from the rules
    assert spec.context == "lighting"      # not given: filled from the rules
    assert spec.follow == []               # given: left for the caller to set
    for name, value in given.items():      # ...which the CLI does next
        if value is not None:
            setattr(spec, name, value)
    assert spec.follow == ["usd:binding"]


def test_rules_prefer_the_approved_revision(tmp_path):
    r = _two_threads(tmp_path)
    save_rules(r, "team.rules", RuleSet(depth=1), "a")          # v001 on @wip
    r.promote("team.rules", "v001", "approved")
    save_rules(r, "team.rules", RuleSet(depth=9), "a")          # v002 on @wip
    loaded, applied = load_rules(r, "team.rules")
    assert loaded.depth == 1 and applied == "team.rules@v001"
    loaded, applied = load_rules(r, "team.rules@wip")
    assert loaded.depth == 9
