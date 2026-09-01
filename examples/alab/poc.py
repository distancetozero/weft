"""Measured compatibility on real geometry: Animal Logic's ALab workbench.

    python examples/alab/poc.py /path/to/ALab-2.3.0/ALab [--out DIR]

The one mechanism in this project with no prior art anywhere is a contract
whose compatibility is *measured*: a provider declares how far each offered
mount may move, and a promotion that moves one further is refused and names
it. Everything before this ran it on a toy car. This runs it on a production
asset -- lab_workbench01, 437 props placed at real transforms.

What is authored, and what is honest about it:

  * Contract surfaces are DERIVED from the assembly (jitsd/extract.py): one
    offer per placement at the assembly's own translate, role = the placed
    asset's name. Props are base-origin (verified from extentsHint), so a
    frame really is where a prop's base sits.
  * The "republish with the shelf moved" is simulated at the interface level:
    the shelf's offers are shifted by a vector. The payload is unchanged.
    Re-modelling ALab is out of scope; the gate only ever reads the surface,
    so it cannot tell the difference -- and that is the point of the design.

Steps: extract -> ingest with interfaces -> bind -> promote -> baseline ->
compatible republish (promotes) -> breaking republish (refused, names offers)
-> drift -> verify.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(HERE))

from jitsd.contracts import Surface  # noqa: E402
from jitsd.extract import provider_interface, read_assembly, write_interfaces  # noqa: E402
from jitsd.ledger import BreakingChange, Repo  # noqa: E402

PROVIDER = "lab_workbench01"
ASSEMBLY = "fragment/assembly/assembly/lab_workbench01/assembly_assembly_lab_workbench01.usda"
ENVELOPE_CM = 1.0
TOLERANCE_FRACTION = 0.10   # a consumer tolerates 10% of its own footprint
GATE_GROUP = "shelf01"


def step(title: str) -> None:
    print("\n== %s" % title)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("alab", help="path to .../ALab-2.3.0/ALab")
    ap.add_argument("--out", default="alab-poc", help="working directory (recreated)")
    args = ap.parse_args()
    A = Path(args.alab)
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    step("extract contract surfaces from the assembly")
    t0 = time.perf_counter()
    ex = read_assembly(str(A / ASSEMBLY), PROVIDER)
    # Consumer tolerances are DERIVED: a stated fraction of each prop's own
    # footprint from its extentsHint. A 6 cm bottle and a 1 cm screw do not
    # tolerate the same drift, and neither value is invented.
    # into_assets: the interface-sublayer convention. Each surface is written
    # INTO the entity's own structure (interface/<a>_interface.usda) and
    # sublayered into its root -- one more department beside modelling/,
    # preview/, surfacing/ -- rather than sitting in a sidecar directory.
    # represent=True makes the contract two-sided: each prop offers its
    # representation set, derived from its own sublayers, and the bench
    # requires it.
    asset_dirs = {a: str(A / "entity" / a) for a in ex.assets
                  if (A / "entity" / a).is_dir()}
    asset_dirs[PROVIDER] = str(A / "entity" / PROVIDER)

    # Everything derived comes first; the interfaces are written from it.
    # reps: the bench's representation requirements, held so every later
    # republish of the bench keeps its two-sided surface -- the first version
    # of this POC dropped them on the ok/mid/bad republishes, which silently
    # stripped the bench's requirements from @approved.
    from jitsd.extract import departments, finish as _finish, materials as _materials
    reps = {}
    for a, d in asset_dirs.items():
        if a == PROVIDER:
            continue
        depts = departments(str(Path(d) / ("%s.usda" % a)))
        if depts:
            reps[a] = depts
    # Shading representations and finish, from the real look layers (Techvar
    # data). The names are uniform across the corpus -- usd_full, usd_preview,
    # usd_preview_proxy -- which makes them a vocabulary, not identity:
    # identity is in the parameters, and the one that separates the corpus is
    # authored opacity (a bottle authors 0.1; a screw authors nothing).
    look_by_asset = {}
    for a in ex.assets:
        lb = (A / "fragment" / "look" / "surfacing" / a / "render_high" / "binding"
              / ("look_surfacing_%s_render_high_binding" % a) / "render_high.usda")
        if lb.exists():
            look_by_asset[a] = str(lb)
    shading_map = {a: m for a in look_by_asset
                   if (m := _materials(look_by_asset[a]))}
    finish_map = {a: f for a in look_by_asset
                  if (f := _finish(look_by_asset[a]))}

    ifaces = write_interfaces(ex, str(out / "iface"), envelope=ENVELOPE_CM,
                              tolerance_fraction=TOLERANCE_FRACTION,
                              represent=True, into_assets=asset_dirs,
                              look_by_asset=look_by_asset)
    n_trans = sum(1 for f in finish_map.values() if f == "translucent")
    print("   shading sets from %d real look layers; finish derived for %d "
          "(%d translucent, %d opaque)"
          % (len(shading_map), len(finish_map), n_trans, len(finish_map) - n_trans))
    if "chemistry_bottle01" in finish_map and "tool_screw01" in finish_map:
        print("   e.g. chemistry_bottle01=%s (opacity 0.1 authored), tool_screw01=%s"
              % (finish_map["chemistry_bottle01"], finish_map["tool_screw01"]))
    print("   %d placements in %d groups -> %d offers, %d consumer surfaces  (%.0f ms)"
          % (len(ex.placements), len(ex.groups), len(ex.placements), len(ex.assets),
             (time.perf_counter() - t0) * 1000))
    for g in ex.groups:
        n = sum(1 for p in ex.placements if p.group == g)
        print("   %-18s %3d mounts" % (g, n))
    tols = {}
    for a in ex.assets:
        text = Path(ifaces[a]).read_text()
        for line in text.splitlines():
            if "tolerance:linear" in line:
                tols[a] = float(line.split("=")[-1])
    if tols:
        lo, hi = min(tols.items(), key=lambda kv: kv[1]), max(tols.items(), key=lambda kv: kv[1])
        print("   consumer tolerances derived for %d/%d props: %s %.2f cm .. %s %.2f cm"
              % (len(tols), len(ex.assets), lo[0], lo[1], hi[0], hi[1]))

    step("ingest: workbench + every placed prop, each with its surface")
    repo = Repo(out / "repo")
    repo.init()
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "workbench", interface=ifaces[PROVIDER])
    missing = []
    for a in ex.assets:
        src = A / "entity" / a / ("%s.usda" % a)
        if not src.exists():
            missing.append(a)
            continue
        repo.save(a, src, "alab", "prop", interface=ifaces[a])
        repo.promote(a, "v001", "approved")
    repo.promote(PROVIDER, "v001", "approved")
    print("   %d assets on @approved" % (1 + len(ex.assets) - len(missing)))
    if missing:
        print("   %d placed assets have no entity layer in this package: %s"
              % (len(missing), ", ".join(missing[:5]) + (" ..." if len(missing) > 5 else "")))

    step("bind: requirements -> offers, by contract and role only")
    res = repo.bind(channel="approved")
    nprov = sum(len(b.providers) for b in res.bindings)
    print("   %d consumers bound to %d offers; ok=%s" % (len(res.bindings), nprov, res.ok))
    for d in res.diagnostics[:5]:
        print("   ! %s" % d)

    step("cut baseline")
    b = repo.cut_baseline(label="alab-workbench-poc", cut_by="poc", channel="approved")
    print("   baseline %s  merkle %s" % (b.number, b.merkle_root[:16]))

    step("republish workbench: %s raised 0.05 cm (inside every tolerance)" % GATE_GROUP)
    ok_iface = out / "iface" / ("%s.ok.usda" % PROVIDER)
    ok_iface.write_text(provider_interface(ex, envelope=ENVELOPE_CM,
                                           nudge={GATE_GROUP: (0.0, 0.05, 0.0)},
                                           represents=reps, shading_required=shading_map))
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "%s +0.05cm" % GATE_GROUP, interface=ok_iface)
    rev, forced = repo.promote(PROVIDER, "@wip", "approved")
    print("   promoted %s -> @approved  (%d violations)" % (rev, len(forced)))

    step("MEASURED, NOT ASSERTED: %s raised 0.7 cm -- inside the provider's %.0f cm "
         "promise" % (GATE_GROUP, ENVELOPE_CM))
    mid_iface = out / "iface" / ("%s.mid.usda" % PROVIDER)
    mid_iface.write_text(provider_interface(ex, envelope=ENVELOPE_CM,
                                            nudge={GATE_GROUP: (0.0, 0.7, 0.0)},
                                            represents=reps, shading_required=shading_map))
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "%s +0.7cm" % GATE_GROUP, interface=mid_iface)
    from jitsd.contracts import check_compatibility
    cur = repo.ledger.channels(PROVIDER)["approved"]
    cand = repo.ledger.resolve_ref(PROVIDER, "@wip")
    old_s = Surface.from_dict(repo.ledger.read_revision(PROVIDER, cur).surface)
    new_s = Surface.from_dict(repo.ledger.read_revision(PROVIDER, cand).surface)
    print("   provider self-check (what it asserted): %d violations"
          % len(check_compatibility(old_s, new_s)))
    re = repo.reevaluate(PROVIDER, cand, "approved")
    print("   consumer re-evaluation (what was measured): %d consumers checked, "
          "%d broken" % (len(re.consumers), len(re.changed)))
    try:
        repo.promote(PROVIDER, "@wip", "approved")
        print("   PROMOTED -- consumers with tolerance < 0.7 cm were not protected. Bug.")
        return 1
    except BreakingChange as e:
        by_consumer = {}
        for v in e.violations:
            by_consumer.setdefault(getattr(v, "consumer", "(provider)"), []).append(v)
        print("   REFUSED by consumers: %d prop%s would break, though the provider kept "
              "its promise" % (len(re.changed), "" if len(re.changed) == 1 else "s"))
        for c in sorted(by_consumer)[:6]:
            v = by_consumer[c][0]
            print("     %-26s %s" % (c, v.detail if hasattr(v, "detail") else v))
        if len(by_consumer) > 6:
            print("     ... and %d more" % (len(by_consumer) - 6))
    print("   @approved still at %s" % repo.ledger.channels(PROVIDER)["approved"])

    step("republish workbench: %s raised 3 cm (past the envelope)" % GATE_GROUP)
    bad_iface = out / "iface" / ("%s.bad.usda" % PROVIDER)
    bad_iface.write_text(provider_interface(ex, envelope=ENVELOPE_CM,
                                            nudge={GATE_GROUP: (0.0, 3.0, 0.0)},
                                            represents=reps, shading_required=shading_map))
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "%s +3cm" % GATE_GROUP, interface=bad_iface)
    try:
        repo.promote(PROVIDER, "@wip", "approved")
        print("   PROMOTED -- the gate did not fire. That is a bug.")
        return 1
    except BreakingChange as e:
        prov = [v for v in e.violations if not hasattr(v, "consumer")]
        cons = [v for v in e.violations if hasattr(v, "consumer")]
        print("   REFUSED: %s %s -> @%s  (%d provider violations, %d consumer violations)"
              % (e.asset, e.rev, e.channel, len(prov), len(cons)))
        for v in prov[:4]:
            print("     %s" % v)
        if len(prov) > 4:
            print("     ... and %d more, every one on %s" % (len(prov) - 4, GATE_GROUP))
    print("   @approved still at %s" % repo.ledger.channels(PROVIDER)["approved"])

    step("impact preview from a slice (docs/10-slices.md): a lighter's slice of the bottles")
    # No closure: the slice is exactly the bottles. With closure, the bottles
    # need the bench and the bench's assembly references every prop, so the
    # slice would be the whole set -- correct, but no blast radius to show.
    from jitsd.slice import SliceSpec, resolve_slice
    sl = resolve_slice(repo, SliceSpec(seeds=["chemistry_bottle*"], closure=[],
                                       channel="approved"))
    members = {m.asset for m in sl.members}
    re = repo.reevaluate(PROVIDER, repo.ledger.resolve_ref(PROVIDER, "@wip"), "approved")
    inside = sorted(c for c in re.changed if c in members)
    outside = sorted(c for c in re.changed if c not in members)
    print("   slice: %d bottles.  candidate %s@wip breaks %d consumers:"
          % (len(members), PROVIDER, len(re.changed)))
    print("     inside the slice  (%d): %s" % (len(inside), ", ".join(inside)))
    print("     outside the slice (%d): %s%s"
          % (len(outside), ", ".join(outside[:5]), " ..." if len(outside) > 5 else ""))
    print("   -- the lighter sees what their edit breaks for other teams, without "
          "loading their slices")

    step("two-sided: a prop republished without its preview department")
    from jitsd.extract import consumer_interface, departments, footprint as _fp
    victim = "chemistry_bottle01"
    vdir = A / "entity" / victim
    deps_now = departments(str(vdir / ("%s.usda" % victim)))
    kept = [d for d in deps_now if d not in ("preview", "interface")]
    fp = _fp(str(vdir / ("%s.usda" % victim)))
    tol = round(fp * TOLERANCE_FRACTION, 4) if fp else None
    stripped = out / "iface" / ("%s.stripped.usda" % victim)
    stripped.write_text(consumer_interface(
        victim, tolerance=tol,
        tolerance_rule="%.0f%% of footprint" % (TOLERANCE_FRACTION * 100),
        provides=kept))
    repo.save(victim, vdir / ("%s.usda" % victim), "alab",
              "dropped preview (simulated at the surface)", interface=stripped)
    try:
        repo.promote(victim, "@wip", "approved")
        print("   PROMOTED -- the bench was not protected. Bug.")
        return 1
    except BreakingChange as e:
        cons = [v for v in e.violations if getattr(v, "consumer", None)]
        print("   REFUSED: %s dropped %s" % (victim, "preview"))
        for v in cons[:3]:
            print("     %s" % v)
        print("   -- the ASSEMBLY is the broken consumer: the contract runs both ways")
    print("   @approved still at %s" % repo.ledger.channels(victim)["approved"])

    step("shading is a binding attribute: tool_screw01 republished without usd_full")
    victim2 = "tool_screw01"
    v2dir = A / "entity" / victim2
    v2fp = _fp(str(v2dir / ("%s.usda" % victim2)))
    v2tol = round(v2fp * TOLERANCE_FRACTION, 4) if v2fp else None
    reduced = [s for s in shading_map.get(victim2, []) if s != "usd_full"]
    noshade = out / "iface" / ("%s.noshade.usda" % victim2)
    noshade.write_text(consumer_interface(
        victim2, tolerance=v2tol,
        tolerance_rule="%.0f%% of footprint" % (TOLERANCE_FRACTION * 100),
        provides=[d for d in departments(str(v2dir / ("%s.usda" % victim2)))],
        shading=reduced, surface_finish=finish_map.get(victim2)))
    repo.save(victim2, v2dir / ("%s.usda" % victim2), "alab",
              "dropped usd_full shading (simulated at the surface)", interface=noshade)
    try:
        repo.promote(victim2, "@wip", "approved")
        print("   PROMOTED -- shading constraint did not protect the bench. Bug.")
        return 1
    except BreakingChange as e:
        cons = [v for v in e.violations if getattr(v, "consumer", None)]
        print("   REFUSED: %s dropped usd_full from its shading set" % victim2)
        for v in cons[:2]:
            print("     %s" % v)
        print("   -- a shading change breaks exactly the consumers bound on shading")
    print("   @approved still at %s" % repo.ledger.channels(victim2)["approved"])

    step("pull one thread: closure by relationship kind, and a team's rule set")
    from jitsd.slice import RuleSet, load_rules, save_rules
    everything = resolve_slice(repo, SliceSpec(seeds=["chemistry_bottle01"], channel="approved"))
    mounts = resolve_slice(repo, SliceSpec(seeds=["chemistry_bottle01"], channel="approved",
                                           follow=["Mount"]))
    print("   seed chemistry_bottle01, follow everything: %d members  (the bench references "
          "every prop)" % len(everything.members))
    print("   seed chemistry_bottle01, follow Mount only: %d members  -> %s"
          % (len(mounts.members), ", ".join(m.asset for m in mounts.members)))
    held = [x for x in mounts.boundary if "not followed" in x.why_excluded]
    print("   declared at the boundary, not pulled: %d threads (%s)"
          % (len(held), ", ".join(sorted({x.why_excluded for x in held}))))
    rev = save_rules(repo, "lookdev.rules",
                     RuleSet(follow=["Mount"], depth=1, view=["position"], label="lookdev"),
                     "dana", "lookdev pulls mounts only, one hop, position in view")
    repo.promote("lookdev.rules", rev, "approved")
    rules, applied = load_rules(repo, "lookdev.rules")
    spec = SliceSpec(seeds=["chemistry_test_tube02"], channel="approved")
    rules.apply(spec, {k: None for k in ("closure", "follow", "depth", "include_optional",
                                         "view", "context")})
    spec.rules = applied
    via_rules = resolve_slice(repo, spec)
    print("   rule set %s saved and promoted; applied to a different seed: %d members"
          % (applied, len(via_rules.members)))

    step("drift since baseline %s" % b.number)
    pins = repo.resolve(channel="approved")
    now = repo.merkle_root(pins)
    print("   baseline %s   now %s   %s"
          % (b.merkle_root[:16], now[:16],
             "DRIFTED (the +0.05cm republish is on @approved)" if now != b.merkle_root else "same"))

    step("verify")
    v = repo.store.verify()
    stale = repo.stale_generators()
    print("   blobs ok %d  corrupt %d  missing %d   stale generators %d"
          % (len(v["ok"]), len(v["corrupt"]), len(v["missing_chunks"]), len(stale)))
    print("\nworking dir: %s" % out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
