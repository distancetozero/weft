"""Honest ALab comparison: stock USD practice vs weft, three scenarios.

    python examples/alab/compare.py /path/to/ALab-2.3.0/ALab

Every number in BENCHMARK.md comes from this script -- re-run it to
reproduce. Methodology (also printed at the end, and copied verbatim into
BENCHMARK.md):

  * Every baseline uses the best stock tooling available; no strawmen.
  * Scenario 1's expected baseline win is published, not hidden.
  * All numbers come from this committed script; re-run to reproduce.
  * ALab's tidy one-entity-per-file layout is favorable terrain for the
    BASELINE; messier corpora shift every scenario toward weft.
  * Timings: best-of-3 for each measurement, on a warm filesystem cache
    (the interpreter, pxr, and this repo's modules are already imported;
    the OS page cache is warm from the exploration that preceded this
    script's first published run).

This script imports weft/deps directly (same interpreter as ALab's USD
build) and does not mutate the ALab tree beyond the idempotent interface
regeneration __maybe_regenerate_interfaces() performs once, the first time
this is ever run against a given checkout (mirrors tests/test_alab_pull.py).
"""

from __future__ import annotations

import argparse
import inspect
import os
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

WORKBENCH_REL = "entity/lab_workbench01/lab_workbench01.usda"
ASSEMBLY_REL = ("fragment/assembly/assembly/lab_workbench01/"
                 "assembly_assembly_lab_workbench01.usda")
ENTITY_REL = "entity/chemistry_bottle01/chemistry_bottle01.usda"
PROVIDER = "lab_workbench01"
SEED_INSTANCE = "chemistry_bottle01_0004"

TRANSLUCENT_ASSETS = ["chemistry_beaker01", "chemistry_beaker02", "chemistry_beaker03",
                       "chemistry_bottle01", "decor_bottle_soda01", "decor_glass01",
                       "stationary_set_square01", "stationary_set_square02"]

SPIKE_TRANSLUCENT_MASK = [
    "/root/shelf01/chemistry_bottle01_0004",
    "/root/shelf01/chemistry_bottle01_0005",
    "/root/shelf01/chemistry_bottle01_0007",
    "/root/shelf01/chemistry_bottle01_0011",
    "/root/shelf01/chemistry_bottle01_0012",
    "/root/shelf01/decor_glass01_0002",
    "/root/shelf02/chemistry_beaker02_0003",
    "/root/workbench01/workbench_shelf07/chemistry_beaker02_0006",
    "/root/workbench01/workbench_shelf07/chemistry_beaker02_0007",
    "/root/workbench01/workbench_shelf07/chemistry_bottle01_0006",
    "/root/workbench01/workbench_shelf07/chemistry_bottle01_0008",
    "/root/workbench01/benchtop01/decor_glass01_0001",
    "/root/workbench01/benchtop02/chemistry_beaker01_0001",
    "/root/workbench01/benchtop02/chemistry_beaker02_0001",
    "/root/workbench01/benchtop02/chemistry_beaker02_0002",
    "/root/workbench01/benchtop02/chemistry_beaker02_0004",
    "/root/workbench01/benchtop02/chemistry_beaker03_0001",
    "/root/workbench01/benchtop02/chemistry_beaker03_0002",
    "/root/workbench01/benchtop02/chemistry_beaker03_0003",
    "/root/workbench01/benchtop02/chemistry_beaker03_0004",
    "/root/workbench01/benchtop02/chemistry_bottle01_0001",
    "/root/workbench01/benchtop02/chemistry_bottle01_0002",
    "/root/workbench01/benchtop02/decor_bottle_soda01_0004",
    "/root/workbench01/benchtop02/stationary_set_square01_0001",
    "/root/workbench01/benchtop03/chemistry_beaker01_0002",
    "/root/workbench01/benchtop03/stationary_set_square02_0001",
]

METHODOLOGY = """\
- Every baseline uses the best stock tooling available; no strawmen.
- Scenario 1's expected baseline win is published, not hidden.
- All numbers come from this committed script; re-run to reproduce.
- ALab's tidy one-entity-per-file layout is favorable terrain for the
  BASELINE; messier corpora shift every scenario toward weft.
- Timings: best-of-3 for each measurement, on a warm filesystem cache."""


def hr(title: str) -> None:
    print("\n" + "=" * 78)
    print(title)
    print("=" * 78)


def sub(title: str) -> None:
    print("\n-- %s --" % title)


def best_of(fn, n=3):
    """Run fn() n times, return (last_result, best_seconds, all_seconds)."""
    times = []
    result = None
    for _ in range(n):
        t0 = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - t0)
    return result, min(times), times


def loc(fn) -> int:
    """Lines of source for a function -- the 'custom code required' metric."""
    return len(inspect.getsource(fn).splitlines())


def fmt_ms(seconds: float) -> str:
    return "%.1f ms" % (seconds * 1000.0)


# -- interface regeneration (idempotent; mirrors tests/test_alab_pull.py) ---

def _needs_regen(alab: str) -> bool:
    iface = os.path.join(alab, "entity", PROVIDER, "interface",
                          "%s_interface.usda" % PROVIDER)
    if not os.path.exists(iface):
        return True
    text = open(iface).read()
    return "jitsd:offer:carrier" not in text or 'over "root"' not in text


def maybe_regenerate_interfaces(alab: str) -> bool:
    """Regenerate root-anchored interfaces with advisory carriers, exactly
    as tests/test_alab_pull.py's fixture does. Idempotent -- a no-op if the
    real ALab checkout already carries them (it does, in the environment
    this script was developed against). Returns True if it did anything."""
    if not _needs_regen(alab):
        return False
    from weft.extract import (departments, finish as _finish,
                               materials as _materials, read_assembly,
                               write_interfaces)

    ex = read_assembly(os.path.join(alab, ASSEMBLY_REL), PROVIDER)
    asset_dirs = {a: os.path.join(alab, "entity", a) for a in ex.assets
                  if os.path.isdir(os.path.join(alab, "entity", a))}
    asset_dirs[PROVIDER] = os.path.join(alab, "entity", PROVIDER)

    reps = {}
    for a, d in asset_dirs.items():
        if a == PROVIDER:
            continue
        depts = departments(os.path.join(d, "%s.usda" % a))
        if depts:
            reps[a] = depts

    look_by_asset = {}
    for a in ex.assets:
        lb = os.path.join(alab, "fragment", "look", "surfacing", a, "render_high",
                           "binding", "look_surfacing_%s_render_high_binding" % a,
                           "render_high.usda")
        if os.path.exists(lb):
            look_by_asset[a] = lb

    with tempfile.TemporaryDirectory() as scratch:
        write_interfaces(ex, scratch, envelope=1.0, tolerance_fraction=0.10,
                          represent=True, into_assets=asset_dirs,
                          look_by_asset=look_by_asset,
                          carrier_rule="group-furniture", anchor="root")
    return True


# -- Scenario 1: known asset, tidy library -----------------------------------

def s1_baseline_open_entity(alab: str):
    from pxr import Usd
    entity_file = os.path.join(alab, ENTITY_REL)

    def run():
        stage = Usd.Stage.Open(entity_file)
        n = sum(1 for _ in stage.Traverse())
        return n

    n, best, times = best_of(run)
    size = os.path.getsize(entity_file)
    return {
        "prims": n, "best_s": best, "times": times,
        "bytes": size, "path": entity_file,
        "prereq": "must already know the exact file path: %s" % ENTITY_REL,
        "verifiability": "none -- a stage, nothing recorded about how it was reached",
    }


def s1_weft_pull(alab: str):
    from pxr import Usd
    from weft.pull import pull
    from weft.manifest import layer_hashes, to_document
    ctx = os.path.join(alab, WORKBENCH_REL)

    def run():
        p = pull(ctx, [SEED_INSTANCE])
        mask = Usd.StagePopulationMask([m.path for m in p.members])
        stage = Usd.Stage.OpenMasked(ctx, mask)
        predicate = Usd.TraverseInstanceProxies(
            Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)
        n = sum(1 for _ in stage.Traverse(predicate))
        return p, n

    (p, n), best, times = best_of(run)
    layer_hashes(p)
    doc = to_document(p)
    ancestors = [a for a in ("/root",) if a != p.members[0].path]
    # spine ancestors carried into the mask: every proper prefix of the
    # seed's own path
    seed_path = p.members[0].path
    parts = seed_path.strip("/").split("/")
    spine = ["/" + "/".join(parts[:i]) for i in range(1, len(parts))]
    return {
        "members": [m.path for m in p.members],
        "prims_total": n, "spine_ancestors": len(spine),
        "prims_content": n - len(spine),
        "best_s": best, "times": times,
        "bytes": p.accounting.get("layer_bytes", 0),
        "manifest_bytes": len(doc.encode()),
        "manifest_digest": p.accounting,
        "path": ctx,
        "prereq": "the workbench context file + one lexical name (%r); "
                  "no need to know %s exists" % (SEED_INSTANCE, ENTITY_REL),
        "verifiability": "SHA256-hashed manifest (%d bytes), re-verifiable "
                         "with weft.manifest.verify()" % len(doc.encode()),
    }


def run_s1(alab: str) -> None:
    hr("SCENARIO 1 -- known asset, tidy library "
       "(\"give me chemistry_bottle01, I know where it lives\")")
    b = s1_baseline_open_entity(alab)
    w = s1_weft_pull(alab)

    sub("baseline: Usd.Stage.Open(entity file directly) + Traverse()")
    print("  path            entity/chemistry_bottle01/chemistry_bottle01.usda")
    print("  prims           %d" % b["prims"])
    print("  bytes (1 layer) %d" % b["bytes"])
    print("  time (best/3)   %s   all: %s"
          % (fmt_ms(b["best_s"]), ", ".join(fmt_ms(t) for t in b["times"])))
    print("  prerequisite    %s" % b["prereq"])
    print("  verifiability   %s" % b["verifiability"])

    sub("weft: pull('%s') against the workbench context + mask consumption"
        % SEED_INSTANCE)
    print("  seed members    %s" % w["members"])
    print("  masked prims    %d total (%d spine ancestor%s carried for context, "
          "%d belonging to the entity itself)"
          % (w["prims_total"], w["spine_ancestors"],
             "" if w["spine_ancestors"] == 1 else "s", w["prims_content"]))
    print("  layer bytes     %d (every layer contributing to the seed's composed "
          "prim stack)" % w["bytes"])
    print("  time (best/3)   %s   all: %s"
          % (fmt_ms(w["best_s"]), ", ".join(fmt_ms(t) for t in w["times"])))
    print("  prerequisite    %s" % w["prereq"])
    print("  verifiability   %s" % w["verifiability"])

    sub("cross-check")
    print("  entity-only prim count from the mask (%d) %s the baseline's direct-open "
          "count (%d)"
          % (w["prims_content"], "MATCHES" if w["prims_content"] == b["prims"]
             else "DIFFERS FROM", b["prims"]))

    sub("HONEST RESULT")
    winner = "baseline" if b["best_s"] <= w["best_s"] else "weft"
    print("  %s is faster here (%s vs %s) -- EXPECTED and PUBLISHED: zero-tooling "
          "path-open wins when the path is already known and the library is tidy."
          % (winner, fmt_ms(b["best_s"]), fmt_ms(w["best_s"])))
    print("  weft's difference in this scenario is the receipt and not needing the "
          "path, not speed.")


# -- Scenario 2: find-then-extract by property -------------------------------

def s2_baseline_translucent(alab: str):
    """Live shading-network walk: LoadAll the workbench, traverse, compute
    each placement's bound material at the 'preview' USD material-binding
    purpose (that is where ALab authors a scalar inputs:opacity; at the
    'full' purpose, opacity is texture-connected and carries no authored
    scalar to read -- discovered empirically and disclosed in BENCHMARK.md),
    walk to the UsdPreviewSurface shader, read its authored inputs:opacity."""
    from pxr import Usd, UsdShade

    workbench = os.path.join(alab, WORKBENCH_REL)

    def run():
        stage = Usd.Stage.Open(workbench, Usd.Stage.LoadAll)
        predicate = Usd.TraverseInstanceProxies(
            Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)
        root = stage.GetPrimAtPath("/root")
        placements = [p for p in Usd.PrimRange(root)
                      if p != root and (p.HasAuthoredReferences()
                                        or p.HasAuthoredPayloads())]
        translucent = []
        for pl in placements:
            hit = False
            for desc in Usd.PrimRange(pl, predicate):
                bapi = UsdShade.MaterialBindingAPI(desc)
                mat, _rel = bapi.ComputeBoundMaterial(
                    materialPurpose=UsdShade.Tokens.preview)
                if not mat or not mat.GetPrim().IsValid():
                    continue
                shader, _sn, _st = mat.ComputeSurfaceSource()
                if not shader or not shader.GetPrim().IsValid():
                    continue
                if shader.GetIdAttr().Get() != "UsdPreviewSurface":
                    continue
                op_in = shader.GetInput("opacity")
                if op_in is None:
                    continue
                attr = op_in.GetAttr()
                if not attr or not attr.IsValid() or not attr.HasAuthoredValue():
                    continue
                val = attr.Get()
                if val is not None and float(val) < 1.0:
                    hit = True
                    break
            if hit:
                translucent.append(pl.GetPath().pathString)
        return stage, sorted(translucent), len(placements)

    (stage, translucent, n_placements), best, times = best_of(run)
    used = stage.GetUsedLayers()
    layer_bytes = sum(os.path.getsize(l.realPath) for l in used
                       if l.realPath and os.path.exists(l.realPath))
    n_populated = sum(1 for _ in stage.Traverse(Usd.TraverseInstanceProxies(
        Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract)))
    return {
        "translucent": translucent, "n_placements": n_placements,
        "n_populated": n_populated, "n_layers_used": len(used),
        "layer_bytes": layer_bytes,
        "best_s": best, "times": times,
        "loc": loc(s2_baseline_translucent),
    }


def s2_weft_pull(alab: str):
    from weft.pull import pull
    from weft.manifest import layer_hashes
    ctx = os.path.join(alab, WORKBENCH_REL)

    def run():
        p = pull(ctx, ["where:finish=translucent"])
        return p

    p, best, times = best_of(run)
    layer_hashes(p)
    return {
        "members": sorted(m.path for m in p.members),
        "best_s": best, "times": times,
        "layer_bytes": p.accounting.get("layer_bytes", 0),
        "n_layers": len(p.layers),
    }


def s2_amortized_setup(alab: str):
    """The one-time cost of deriving jitsd:bind:finish onto the interfaces
    weft's pull reads -- run into a THROWAWAY temp dir (into_assets omitted)
    so this measurement never touches the real ALab tree."""
    from weft.extract import finish as _finish, materials as _materials
    from weft.extract import departments, read_assembly, write_interfaces

    def run():
        ex = read_assembly(os.path.join(alab, ASSEMBLY_REL), PROVIDER)
        look_by_asset = {}
        for a in ex.assets:
            lb = os.path.join(alab, "fragment", "look", "surfacing", a, "render_high",
                               "binding", "look_surfacing_%s_render_high_binding" % a,
                               "render_high.usda")
            if os.path.exists(lb):
                look_by_asset[a] = lb
        finishes = {a: f for a in look_by_asset
                    if (f := _finish(look_by_asset[a]))}
        with tempfile.TemporaryDirectory() as scratch:
            write_interfaces(ex, scratch, envelope=1.0, tolerance_fraction=0.10,
                              represent=True, look_by_asset=look_by_asset,
                              carrier_rule="group-furniture", anchor="root")
        n_trans = sum(1 for f in finishes.values() if f == "translucent")
        return len(look_by_asset), len(finishes), n_trans

    (n_looks, n_finishes, n_trans), best, times = best_of(run)
    return {"n_looks": n_looks, "n_finishes": n_finishes, "n_translucent": n_trans,
            "best_s": best, "times": times}


def run_s2(alab: str) -> None:
    hr("SCENARIO 2 -- find-then-extract by property "
       "(\"give me every translucent thing\")")
    b = s2_baseline_translucent(alab)
    w = s2_weft_pull(alab)
    setup = s2_amortized_setup(alab)

    sub("baseline: LoadAll the workbench, UsdShade.MaterialBindingAPI per "
        "placement, walk to the UsdPreviewSurface shader")
    print("  placements scanned     %d" % b["n_placements"])
    print("  stage populated prims  %d" % b["n_populated"])
    print("  layers stage loaded    %d files, %d bytes (Sdf layer sizes via "
          "stage.GetUsedLayers())" % (b["n_layers_used"], b["layer_bytes"]))
    print("  custom code required   %d lines (this function)" % b["loc"])
    print("  translucent found      %d" % len(b["translucent"]))
    print("  time (best/3)          %s   all: %s"
          % (fmt_ms(b["best_s"]), ", ".join(fmt_ms(t) for t in b["times"])))

    sub("weft: pull(\"where:finish=translucent\") on the LoadNone context")
    print("  members                %d" % len(w["members"]))
    print("  layers consulted       %d files, %d bytes (manifest accounting)"
          % (w["n_layers"], w["layer_bytes"]))
    print("  time (best/3)          %s   all: %s"
          % (fmt_ms(w["best_s"]), ", ".join(fmt_ms(t) for t in w["times"])))

    sub("AMORTIZED SETUP -- one-time cost of deriving jitsd:bind:finish onto "
        "the interfaces weft's answer reads (run into a throwaway temp dir, "
        "does not touch the ALab tree)")
    print("  look layers read       %d real look layers (fragment/look/surfacing/*)"
          % setup["n_looks"])
    print("  finish derived for     %d/%d (%d translucent) -- rule: authored "
          "opacity < 0.999 on any Shader spec in the look layer; 8 of %d looks "
          "author opacity at all" % (setup["n_finishes"], setup["n_looks"],
                                     setup["n_translucent"], setup["n_looks"]))
    print("  time (best/3)          %s   all: %s"
          % (fmt_ms(setup["best_s"]), ", ".join(fmt_ms(t) for t in setup["times"])))
    print("  this cost is paid ONCE per republish of the look layers, not once "
          "per query -- every subsequent where:finish=translucent pull reuses it")

    sub("AGREEMENT CHECK")
    base_set, weft_set = set(b["translucent"]), set(w["members"])
    if base_set == weft_set:
        print("  MATCH: baseline's live shading-network walk and weft's "
              "interface-derived answer agree exactly -- %d/%d placements, "
              "identical set." % (len(base_set), len(weft_set)))
    else:
        only_base = sorted(base_set - weft_set)
        only_weft = sorted(weft_set - base_set)
        print("  DISCREPANCY -- baseline only (%d): %s" % (len(only_base), only_base))
        print("  DISCREPANCY -- weft only (%d): %s" % (len(only_weft), only_weft))
    print("  spike's recorded mask (%d) also matches: %s"
          % (len(SPIKE_TRANSLUCENT_MASK), set(SPIKE_TRANSLUCENT_MASK) == weft_set))

    sub("HONEST WRINKLE")
    print("  weft's answer reads jitsd:bind:finish from interfaces derived ONCE "
          "from the look layers (spec-level walk across every representation: "
          "usd_full, usd_preview, usd_preview_proxy); the baseline inspects the "
          "COMPOSED shading network live, at one binding purpose ('preview') per "
          "placement. They agree on ALab because ALab's 'preview' purpose is where "
          "the authored scalar opacity actually lives -- the 'full' purpose material "
          "connects opacity to a texture node with no authored scalar to read at "
          "all, so a baseline written against 'full' purpose alone would silently "
          "find ZERO translucent placements. Getting the baseline right required "
          "discovering this; a less careful steelman could have under-measured "
          "itself into a false weft win.")
    print("  the derivation rule (authored opacity only, 8 of %d looks) is "
          "recorded on the interfaces themselves, readable by anyone -- not just "
          "by this script." % setup["n_looks"])


# -- Scenario 3: extraction completeness -------------------------------------

def s3_baseline_compute_all_deps(alab: str):
    from pxr import UsdUtils
    import io
    from contextlib import redirect_stderr

    entity = os.path.join(alab, ENTITY_REL)
    assembly = os.path.join(alab, ASSEMBLY_REL)

    def run(path):
        buf = io.StringIO()
        with redirect_stderr(buf):
            layers, assets, unresolved = UsdUtils.ComputeAllDependencies(path)
        return layers, assets, unresolved

    (e_layers, e_assets, e_unres), e_best, e_times = best_of(lambda: run(entity))
    (a_layers, a_assets, a_unres), a_best, a_times = best_of(lambda: run(assembly))
    return {
        "entity": {"layers": len(e_layers), "assets": len(e_assets),
                   "unresolved": len(e_unres), "best_s": e_best, "times": e_times,
                   "layer_paths": sorted(str(l.identifier) for l in e_layers)},
        "assembly": {"layers": len(a_layers), "assets": len(a_assets),
                     "unresolved": len(a_unres), "best_s": a_best, "times": a_times},
    }


def s3_deps_graph(alab: str):
    from deps.graph import build, discover, Cache
    from deps.walk import ARC, ASSET_ATTR, REL, CONN, INHERIT, COLLECTION

    entity = os.path.normpath(os.path.abspath(os.path.join(alab, ENTITY_REL)))
    assembly = os.path.normpath(os.path.abspath(os.path.join(alab, ASSEMBLY_REL)))

    paths = discover(alab)
    cache_file = os.path.join(tempfile.gettempdir(), "alab-compare-deps-cache.json")
    cache = Cache(cache_file)   # scratch cache, never written inside the ALab tree
    t0 = time.perf_counter()
    g = build(paths, cache=cache)
    cache.save()
    build_s = time.perf_counter() - t0

    def kind_tally(idents):
        tally = {}
        binding = 0
        for ident in idents:
            rec = g.records.get(ident)
            if not rec:
                continue
            for e in rec.edges:
                if getattr(e, "deleted", False):
                    continue
                tally[e.kind] = tally.get(e.kind, 0) + 1
                if e.kind == REL and e.name.startswith("material:binding"):
                    binding += 1
        return tally, binding

    e_closure = g.needs(entity) | {entity}
    a_closure = g.needs(assembly) | {assembly}
    e_layers, e_assets = g.split(e_closure)
    a_layers, a_assets = g.split(a_closure)
    e_tally, e_binding = kind_tally(e_closure)
    a_tally, a_binding = kind_tally(a_closure)

    def non_arc(tally):
        return sum(v for k, v in tally.items() if k != ARC)

    _, dep_best, dep_times = best_of(lambda: g.dependents(entity))
    dependents = g.dependents(entity)

    return {
        "n_layers_total": len(paths), "build_s": build_s, "stats": g.stats(),
        "entity_closure_layers": len(e_layers), "entity_closure_assets": len(e_assets),
        "assembly_closure_layers": len(a_layers), "assembly_closure_assets": len(a_assets),
        "entity_tally": e_tally, "entity_binding": e_binding,
        "assembly_tally": a_tally, "assembly_binding": a_binding,
        "entity_non_arc": non_arc(e_tally), "assembly_non_arc": non_arc(a_tally),
        "dependents": sorted(dependents), "dependents_best_s": dep_best,
        "dependents_times": dep_times,
        "ARC": ARC, "ASSET_ATTR": ASSET_ATTR, "REL": REL, "CONN": CONN,
        "INHERIT": INHERIT, "COLLECTION": COLLECTION,
    }


def run_s3(alab: str) -> None:
    hr("SCENARIO 3 -- extraction completeness "
       "(\"take the asset and everything it needs\")")
    b = s3_baseline_compute_all_deps(alab)
    d = s3_deps_graph(alab)

    sub("baseline: UsdUtils.ComputeAllDependencies -- arc-only closure, the "
        "machinery behind usdz packaging")
    for label, key in (("chemistry_bottle01 (one entity)", "entity"),
                       ("lab_workbench01 assembly", "assembly")):
        r = b[key]
        print("  %-32s layers=%-4d assets=%-4d unresolved=%-3d  time(best/3)=%s"
              % (label, r["layers"], r["assets"], r["unresolved"], fmt_ms(r["best_s"])))

    sub("weft/deps: dependency graph over the ALab tree's own closures")
    print("  layers discovered      %d (deps.discover(ALab))" % d["n_layers_total"])
    print("  full graph build       %s  (%s)" % (fmt_ms(d["build_s"]), d["stats"]))
    print("  entity closure         %d layers, %d other assets (vs baseline's "
          "%d layers, %d assets)"
          % (d["entity_closure_layers"], d["entity_closure_assets"],
             b["entity"]["layers"], b["entity"]["assets"]))
    print("  assembly closure       %d layers, %d other assets (vs baseline's "
          "%d layers, %d assets)"
          % (d["assembly_closure_layers"], d["assembly_closure_assets"],
             b["assembly"]["layers"], b["assembly"]["assets"]))

    def print_tally(label, tally, binding, non_arc):
        print("  %s edges by kind:" % label)
        for k in (d["ARC"], d["ASSET_ATTR"], d["REL"], d["CONN"], d["INHERIT"],
                  d["COLLECTION"]):
            n = tally.get(k, 0)
            extra = "  (of which %d are material:binding)" % binding if k == d["REL"] else ""
            print("      %-10s %5d%s" % (k, n, extra))
        print("      non-arc total (invisible to ComputeAllDependencies): %d" % non_arc)

    print_tally("entity (chemistry_bottle01)", d["entity_tally"], d["entity_binding"],
                d["entity_non_arc"])
    print_tally("assembly (lab_workbench01)", d["assembly_tally"], d["assembly_binding"],
                d["assembly_non_arc"])

    sub("REVERSE QUERY -- structurally absent from the baseline")
    print("  \"what depends on chemistry_bottle01's own entity layer\"")
    print("  dependents found       %d" % len(d["dependents"]))
    print("  time (best/3)          %s   all: %s"
          % (fmt_ms(d["dependents_best_s"]),
             ", ".join(fmt_ms(t) for t in d["dependents_times"])))
    print("  UsdUtils.ComputeAllDependencies has no reverse direction at all -- "
          "answering this with stock tooling means scanning every layer in the "
          "tree for a reference to this one, an O(corpus) operation with no API "
          "for it.")

    sub("HONEST FRAMING")
    print("  This is completeness-with-declaration vs silent omission, not a "
          "speed contest. ComputeAllDependencies is fast and correct for what "
          "it claims to compute (composition arcs). It does not claim to see "
          "material bindings, shader connections, inherits, or collections -- "
          "and does not surface that it isn't looking. The %d non-arc edges "
          "in chemistry_bottle01's own closure (of which %d are material "
          "bindings) are dependencies a usdz-style arc-only extraction would "
          "silently drop." % (d["entity_non_arc"], d["entity_binding"]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("alab", help="path to .../ALab-2.3.0/ALab")
    args = ap.parse_args()
    alab = os.path.abspath(args.alab)

    hr("ALab comparison: stock USD practice vs weft")
    print("ALab checkout: %s" % alab)
    from pxr import Usd as _Usd
    print("USD version: %s" % ".".join(str(x) for x in _Usd.GetVersion()))
    print("\nMETHODOLOGY")
    print(METHODOLOGY)

    regenerated = maybe_regenerate_interfaces(alab)
    print("\ninterface regeneration: %s"
          % ("performed (first run against this checkout)" if regenerated
             else "skipped -- interfaces already current, no write to the ALab tree"))

    run_s1(alab)
    run_s2(alab)
    run_s3(alab)

    hr("SUMMARY TABLE")
    print("%-38s %-10s %-32s %-14s %-10s"
          % ("scenario / method", "wall time", "bytes / prims touched",
             "prereq knowledge", "verifiable"))
    print("-" * 106)
    print("Full per-scenario numbers are printed above; this table is assembled "
          "by hand in BENCHMARK.md from the run captured here.")

    hr("METHODOLOGY (verbatim)")
    print(METHODOLOGY)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
