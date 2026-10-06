#!/usr/bin/env python
"""Hard numbers on the weft thesis: is working surgically MORE convenient than
loading the whole stage? Each scenario runs in its OWN subprocess so peak RSS
(memory) is clean per-scenario.

Scenarios:
  scale     open LoadNone; how big is ALab, how much sits behind payloads
  full      open + load EVERYTHING (the "load the whole thing" baseline):
            wall time, peak RSS, prim/gprim counts
  surgical  weft pull a representative asset's closure -> OpenMasked + load:
            pull time, mask size, open+load time, peak RSS, prim/gprim counts
  data      weft data cheap projection of the WHOLE stage with NO load:
            time, rows, prims/sec, peak RSS  (query the scene as data for free)

Usage:
  python bench_alab.py report                 # discover seed, run all, tabulate
  python bench_alab.py <mode> <entry> [seed]  # one scenario -> JSON (internal)
"""
import glob
import json
import os
import resource
import subprocess
import sys
import time

# Portable: repo root is three dirs up from extras/bench/ (override WEFT_REPO);
# the USD-capable interpreter defaults to the one running this (override WEFT_PY);
# ALab lives wherever WEFT_ALAB points (default ~/weft-demo/alab).
WEFT = os.environ.get(
    "WEFT_REPO",
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
ENV_PY = os.environ.get("WEFT_PY", sys.executable)
ALAB = os.environ.get("WEFT_ALAB", os.path.expanduser("~/weft-demo/alab"))

sys.path.insert(0, WEFT)


def maxrss_mb():
    # macOS ru_maxrss is bytes; Linux is KiB. Detect by magnitude.
    v = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return v / (1024 * 1024) if v > 1 << 20 else v / 1024


def _predicate(Usd):
    return Usd.PrimIsActive & Usd.PrimIsDefined & ~Usd.PrimIsAbstract


def mode_scale(entry, seed=None):
    from pxr import Usd
    t = time.perf_counter()
    s = Usd.Stage.Open(entry, Usd.Stage.LoadNone)
    t_open = time.perf_counter() - t
    prims = list(s.Traverse(Usd.TraverseInstanceProxies(_predicate(Usd))))
    payloaded = sum(1 for p in prims if p.HasAuthoredPayloads())
    return {"mode": "scale", "open_loadnone_s": round(t_open, 4),
            "prims_unloaded": len(prims), "payloaded_prims": payloaded,
            "maxrss_mb": round(maxrss_mb(), 1)}


def _read_points(prims, UsdGeom):
    """Force-materialise geometry: sum points over PointBased gprims (this is
    what a consumer/renderer actually pays -- composition alone is lazy)."""
    gp = pts = 0
    for p in prims:
        pb = UsdGeom.PointBased(p)
        if not pb:
            continue
        gp += 1
        v = pb.GetPointsAttr().Get()
        if v is not None:
            pts += len(v)
    return gp, pts


def mode_full(entry, seed=None):
    from pxr import Usd, UsdGeom
    t = time.perf_counter()
    s = Usd.Stage.Open(entry)      # default: populate + load all payloads
    s.Load()
    t_compose = time.perf_counter() - t
    prims = list(s.Traverse(Usd.TraverseInstanceProxies(_predicate(Usd))))
    t2 = time.perf_counter()
    gp, pts = _read_points(prims, UsdGeom)   # actually hold the geometry
    t_read = time.perf_counter() - t2
    return {"mode": "full", "compose_s": round(t_compose, 3),
            "read_geo_s": round(t_read, 3), "total_s": round(t_compose + t_read, 3),
            "prims_loaded": len(prims), "gprims": gp, "points": pts,
            "maxrss_mb": round(maxrss_mb(), 1)}


def mode_surgical(entry, seed):
    from pxr import Usd, UsdGeom
    from weft.pull import pull
    # seed arrives as a bare path; pull's grammar needs the `path:` plane.
    seed_expr = seed if ":" in seed.split("/")[0] else "path:" + seed
    t = time.perf_counter()
    p = pull(entry, [seed_expr], depth=12)    # compute the minimal closure
    t_pull = time.perf_counter() - t
    paths = [m.path for m in p.members]
    t2 = time.perf_counter()
    s = Usd.Stage.OpenMasked(entry, Usd.StagePopulationMask(paths))
    s.Load()                                  # load the masked members only
    t_open = time.perf_counter() - t2
    prims = list(s.Traverse(Usd.TraverseInstanceProxies(_predicate(Usd))))
    t3 = time.perf_counter()
    gp, pts = _read_points(prims, UsdGeom)    # hold just this slice's geometry
    t_read = time.perf_counter() - t3
    return {"mode": "surgical", "seed": seed_expr, "pull_s": round(t_pull, 3),
            "mask_members": len(paths), "open_masked_load_s": round(t_open, 3),
            "read_geo_s": round(t_read, 3),
            "total_s": round(t_pull + t_open + t_read, 3),
            "prims_in_surgical": len(prims), "gprims": gp, "points": pts,
            "maxrss_mb": round(maxrss_mb(), 1)}


def mode_data(entry, seed=None):
    from pxr import Usd
    from weft import data
    s = Usd.Stage.Open(entry, Usd.Stage.LoadNone)
    t = time.perf_counter()
    tbl = data.project(s)                     # cheap tier, NO payload load
    t_proj = time.perf_counter() - t
    n = len(tbl.rows())
    return {"mode": "data", "project_cheap_s": round(t_proj, 3), "rows": n,
            "prims_per_s": round(n / t_proj) if t_proj else 0,
            "maxrss_mb": round(maxrss_mb(), 1)}


MODES = {"scale": mode_scale, "full": mode_full,
         "surgical": mode_surgical, "data": mode_data}


def find_entry():
    for pat in ("**/entry.usda", "**/entry.usd", "**/*entry*.usd*"):
        hits = sorted(glob.glob(os.path.join(ALAB, pat), recursive=True))
        if hits:
            return hits[0]
    return None


def discover_seed(entry):
    """Pick a real asset to pull -- NOT the scene root (masking an ancestor
    pulls its whole subtree). Measure each candidate the way the benchmark will:
    by the actual masked+loaded prim count. Choose the payloaded asset placement
    (depth>=3, not root) whose masked size is closest to ~3% of the scene, within
    [100, 15%]. Measuring directly avoids the instance-proxy counting mismatch."""
    from pxr import Usd
    pred = _predicate(Usd)
    full = Usd.Stage.Open(entry)
    full.Load()
    total = sum(1 for _ in full.Traverse(Usd.TraverseInstanceProxies(pred)))

    cands = [p.GetPath().pathString for p in full.Traverse(pred)
             if p.HasAuthoredPayloads() and p.GetPath().pathString.count("/") >= 3]
    step = max(1, len(cands) // 40)
    sample = cands[::step][:40]

    target, lo, hi = 0.03 * total, 100, 0.15 * total
    best, best_n, best_d = None, 0, 1e18
    for path in sample:
        m = Usd.Stage.OpenMasked(entry, Usd.StagePopulationMask([path]))
        m.Load()
        n = sum(1 for _ in m.Traverse(Usd.TraverseInstanceProxies(pred)))
        if lo <= n <= hi and abs(n - target) < best_d:
            best, best_n, best_d = path, n, abs(n - target)
    return best, total, best_n


def run_mode_subproc(mode, entry, seed=None):
    env = dict(os.environ, PYTHONPATH=WEFT)
    cmd = [ENV_PY, os.path.abspath(__file__), mode, entry] + ([seed] if seed else [])
    out = subprocess.run(cmd, env=env, capture_output=True, text=True)
    line = [l for l in out.stdout.splitlines() if l.startswith("{")]
    if not line:
        return {"mode": mode, "error": (out.stderr or out.stdout)[-500:]}
    return json.loads(line[-1])


def report():
    entry = find_entry()
    if not entry:
        print("no entry.usda under %s -- extract ALab first" % ALAB)
        return 1
    print("ALab entry: %s\n" % entry)
    seed, total, seed_n = discover_seed(entry)
    if not seed:
        print("could not find a representative asset to pull")
        return 1
    print("surgical seed: %s  (its loaded subtree ~%d prims)\n" % (seed, seed_n))

    results = {}
    for mode in ("scale", "data", "surgical", "full"):
        print("running %s ..." % mode, flush=True)
        results[mode] = run_mode_subproc(mode, entry, seed if mode == "surgical" else None)

    print("\n================ HARD NUMBERS ================\n")
    for mode in ("scale", "data", "surgical", "full"):
        r = results[mode]
        print("[%s]" % mode)
        for k, v in r.items():
            if k != "mode":
                print("   %-22s %s" % (k, v))
        print()

    f, s = results.get("full", {}), results.get("surgical", {})
    d = results.get("data", {})
    if "total_s" in f and "total_s" in s:
        print("---------------- the convenience delta ----------------")
        ft, st = f["total_s"], s["total_s"]
        fm, sm = f.get("maxrss_mb", 1), s.get("maxrss_mb", 1)
        fp, sp = f.get("prims_loaded", 1), s.get("prims_in_surgical", 0)
        print("  full (load+read ALL): %7.2fs   %7.0f MB   %6d prims   %d pts"
              % (ft, fm, fp, f.get("points", 0)))
        print("  surgical slice:       %7.2fs   %7.0f MB   %6d prims   %d pts"
              % (st, sm, sp, s.get("points", 0)))
        if st > 0:
            print("  -> %.1fx faster, %.1fx lighter, %.1f%% of the prims"
                  % (ft / st, fm / max(sm, 1e-9), 100.0 * sp / max(fp, 1)))
    if "project_cheap_s" in d:
        print("  query the WHOLE scene as data, no load: %.2fs for %d prims (%d/s), %.0f MB"
              % (d["project_cheap_s"], d.get("rows", 0), d.get("prims_per_s", 0),
                 d.get("maxrss_mb", 0)))
    return 0


def sweep():
    """Map the convenience curve: pull progressively larger slices (an asset,
    then its shelf, bench, workbench, set) and watch time/RAM/prims grow toward
    the full-load baseline -- where does surgical stop being a win?"""
    entry = find_entry()
    if not entry:
        print("no entry.usda under %s" % ALAB); return 1
    seed, total, seed_n = discover_seed(entry)
    if not seed:
        print("no asset found"); return 1

    # ancestor chain from the asset up to the set (each a bigger masked slice)
    parts = seed.strip("/").split("/")
    chain = []
    for depth in range(len(parts), 1, -1):
        p = "/" + "/".join(parts[:depth])
        if p.count("/") >= 2:                 # skip /root (the whole scene)
            chain.append(p)
    chain = list(dict.fromkeys(chain))        # dedupe, keep order (deep->shallow)

    print("ALab: %s  (scene %d prims unloaded)\n" % (entry, total))
    full = run_mode_subproc("full", entry)
    fp = full.get("prims_loaded", 1); ft = full.get("total_s", 1); fm = full.get("maxrss_mb", 1)
    fpts = full.get("points", 1)

    rows = []
    for path in chain:
        r = run_mode_subproc("surgical", entry, path)
        if "error" in r:
            continue
        rows.append((path, r))

    print("\n================ SLICE SWEEP ================")
    print("full baseline: %.2fs  %.0f MB  %d prims  %d pts\n" % (ft, fm, fp, fpts))
    hdr = ("slice", "prims", "%scene", "pts", "%pts", "total_s", "RAM_MB", "x_faster", "x_lighter")
    print("%-26s %7s %7s %10s %6s %8s %7s %9s %10s" % hdr)
    for path, r in rows:
        name = path.split("/")[-1][:26]
        pr = r.get("prims_in_surgical", 0); pts = r.get("points", 0)
        st = r.get("total_s", 0); sm = r.get("maxrss_mb", 0)
        print("%-26s %7d %6.1f%% %10d %5.1f%% %8.3f %7.0f %9.1f %10.1f"
              % (name, pr, 100.0*pr/fp, pts, 100.0*pts/max(fpts,1), st, sm,
                 ft/max(st,1e-9), fm/max(sm,1e-9)))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "report":
        sys.exit(report())
    if len(sys.argv) >= 2 and sys.argv[1] == "sweep":
        sys.exit(sweep())
    mode, entry = sys.argv[1], sys.argv[2]
    seed = sys.argv[3] if len(sys.argv) > 3 else None
    print(json.dumps(MODES[mode](entry, seed)))
