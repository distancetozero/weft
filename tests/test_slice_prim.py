"""Prim selections in slices, with the authority rule (spec section 9).

The ask grammar as slice-seed syntax scoped by a context asset: a seed of
the form "<context>:<ask>" resolves to a two-tier membership -- the context
asset joins the slice like any other seed, and its Selection records which
prims the ask picked out at the coordinate's pinned revision, priced from
the pull manifest's own accounting. `resolve_slice` always re-runs the ask;
a spec loaded via `--from` may carry a recorded Selection, and the
authority rule governs what happens when the replay disagrees with it.
"""

from __future__ import annotations

import textwrap

import pytest

pxr = pytest.importorskip("pxr")

from weft.ledger import Repo
from weft.slice import (Selection, SliceSpec, is_prim_seed, resolve_slice,
                         split_prim_seed)


def _repo(tmp_path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.init()
    return r


def _usda(tmp_path, name, text):
    p = tmp_path / ("%s.usda" % name)
    p.write_text(textwrap.dedent(text).lstrip())
    return p


BENCH_SRC = '''
    #usda 1.0
    (
        defaultPrim = "root"
    )

    def Xform "root"
    {
        def Xform "bottle_0001"
        {
            uniform token finish = "translucent"
        }
        def Xform "bottle_0002"
        {
        }
    }
'''


def _bench_repo(tmp_path):
    r = _repo(tmp_path)
    src = _usda(tmp_path, "bench", BENCH_SRC)
    r.save("bench", src, "t", "ingest")
    r.promote("bench", "wip", "approved")
    return r, src


# -- is_prim_seed / split_prim_seed: the context/asset seed boundary -------

def test_prim_seed_detection():
    assert is_prim_seed("lab_workbench01:where:finish=translucent")
    assert is_prim_seed("bench:path:/root/x")
    assert not is_prim_seed("chemistry_bottle01")          # plain asset seed
    assert not is_prim_seed("provides:Mount@1")            # asset-level predicate
    assert not is_prim_seed("author:x")                    # asset-level predicate
    assert split_prim_seed("bench:where:finish=translucent") == (
        "bench", "where:finish=translucent")


def test_prim_seed_detection_does_not_misclassify_asset_seeds():
    """Every existing asset-level seed form stays an asset seed when it has
    no context prefix -- only "<context>:<plane>:..." is a prim seed."""
    for asset_seed in ("provides:Mount@1", "requires:Mount@2", "role:R",
                       "author:A", "changed-since:baseline_1", "box:0,0,0,1,1,1"):
        assert not is_prim_seed(asset_seed), asset_seed
    for prim_seed in ("bench:role:propSocket", "bench:name:bottle_0001",
                      "bench:offers:Mount@1", "bench:requires:Mount@1",
                      "bench:id:0001", "bench:near:/root/x"):
        assert is_prim_seed(prim_seed), prim_seed


# -- end-to-end resolution ---------------------------------------------------

def test_selection_resolves_and_prices(tmp_path):
    r, _src = _bench_repo(tmp_path)
    spec = SliceSpec(seeds=["bench:where:finish=translucent"])
    result = resolve_slice(r, spec)
    assert len(result.selections) == 1
    sel = result.selections[0]
    assert sel.context == "bench"
    assert sel.paths == ["/root/bottle_0001"]
    assert sel.layer_bytes > 0
    assert sel.ask == "where:finish=translucent"


def test_selection_context_asset_joins_membership(tmp_path):
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["bench:where:finish=translucent"]))
    assert "bench" in {m.asset for m in result.members}


def test_selection_matching_nothing_is_diagnosed_not_errored(tmp_path):
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["bench:where:finish=opaque"]))
    (sel,) = result.selections
    assert sel.paths == []
    assert any("matched nothing" in d for d in result.diagnostics)
    assert result.ok


# -- context resolution failures --------------------------------------------

def test_prim_seed_unknown_context_is_an_error(tmp_path):
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["no_such_asset:where:finish=translucent"]))
    assert not result.ok
    assert result.selections == []
    assert any("no context asset" in d for d in result.diagnostics)


def test_prim_seed_context_with_no_source_is_an_error(tmp_path):
    """A generator-backed asset has no source file at all (_AssetInfo.source
    is None) -- the same diagnostic-plus-error path as a missing file."""
    r = _repo(tmp_path)
    from weft.generators import vehicle  # noqa: F401 -- registers "vehicle"
    r.declare("chassis", "chassis@1.0.0", None, "alice")
    r.promote("chassis", "wip", "approved")
    result = resolve_slice(r, SliceSpec(seeds=["chassis:where:finish=translucent"]))
    assert not result.ok
    assert result.selections == []
    assert any("has no source file" in d for d in result.diagnostics)


def test_prim_seed_malformed_ask_is_a_diagnostic_not_a_crash(tmp_path):
    """The slice contract: failures are diagnostics, never crashes. A
    malformed ask (near: wants SEED,RADIUS) must not propagate a ValueError
    out of resolve_slice."""
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["bench:near:/root/x"]))
    assert not result.ok
    assert result.selections == []
    assert any("prim seed" in d and "near: wants SEED,RADIUS" in d
               for d in result.diagnostics)


def test_prim_seed_context_source_missing_on_disk_is_an_error(tmp_path):
    """The recorded source path exists in the revision but the file itself
    is gone from disk -- must be handled the same as a None source."""
    r, src = _bench_repo(tmp_path)
    src.unlink()
    result = resolve_slice(r, SliceSpec(seeds=["bench:where:finish=translucent"]))
    assert not result.ok
    assert result.selections == []
    assert any("has no source file" in d for d in result.diagnostics)


# -- the authority rule -------------------------------------------------------

def test_authority_rule_same_rev_mismatch_is_an_error(tmp_path):
    r, _src = _bench_repo(tmp_path)
    spec = SliceSpec(
        seeds=["bench:where:finish=translucent"],
        selections=[{"context": "bench", "rev": "v001",
                    "ask": "where:finish=translucent",
                    "paths": ["/root/bottle_0002"]}])   # wrong on purpose
    result = resolve_slice(r, spec)
    assert not result.ok
    assert any("invariant violated" in d for d in result.diagnostics)


def test_authority_rule_same_rev_match_is_clean(tmp_path):
    r, _src = _bench_repo(tmp_path)
    spec = SliceSpec(
        seeds=["bench:where:finish=translucent"],
        selections=[{"context": "bench", "rev": "v001",
                    "ask": "where:finish=translucent",
                    "paths": ["/root/bottle_0001"]}])
    result = resolve_slice(r, spec)
    assert result.ok
    assert not any("invariant violated" in d for d in result.diagnostics)


def test_authority_rule_different_rev_is_drift_diagnostic_never_an_error(tmp_path):
    r, _src = _bench_repo(tmp_path)
    spec = SliceSpec(
        seeds=["bench:where:finish=translucent"],
        selections=[{"context": "bench", "rev": "v000",   # a rev that never existed
                    "ask": "where:finish=translucent",
                    "paths": ["/root/bottle_0002"]}])
    result = resolve_slice(r, spec)
    assert result.ok                          # drift is never an error
    assert any("selection drift" in d and "ask is authoritative" in d
               for d in result.diagnostics)


# -- receipt ------------------------------------------------------------------

def test_receipt_prints_selections(tmp_path):
    from weft.slice import receipt
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["bench:where:finish=translucent"]))
    text = receipt(result)
    assert "selections (1):" in text
    assert "bench@v001 : where:finish=translucent -> 1 prims" in text


def test_receipt_omits_selections_block_when_empty(tmp_path):
    from weft.slice import receipt
    r, _src = _bench_repo(tmp_path)
    result = resolve_slice(r, SliceSpec(seeds=["bench"]))
    assert "selections" not in receipt(result)
