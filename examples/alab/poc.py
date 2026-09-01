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
    ifaces = write_interfaces(ex, str(out / "iface"), envelope=ENVELOPE_CM,
                              tolerance_fraction=TOLERANCE_FRACTION)
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
                                           nudge={GATE_GROUP: (0.0, 0.05, 0.0)}))
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "%s +0.05cm" % GATE_GROUP, interface=ok_iface)
    rev, forced = repo.promote(PROVIDER, "@wip", "approved")
    print("   promoted %s -> @approved  (%d violations)" % (rev, len(forced)))

    step("MEASURED, NOT ASSERTED: %s raised 0.7 cm -- inside the provider's %.0f cm "
         "promise" % (GATE_GROUP, ENVELOPE_CM))
    mid_iface = out / "iface" / ("%s.mid.usda" % PROVIDER)
    mid_iface.write_text(provider_interface(ex, envelope=ENVELOPE_CM,
                                            nudge={GATE_GROUP: (0.0, 0.7, 0.0)}))
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
                                            nudge={GATE_GROUP: (0.0, 3.0, 0.0)}))
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
