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

from jitsd.extract import provider_interface, read_assembly, write_interfaces  # noqa: E402
from jitsd.ledger import BreakingChange, Repo  # noqa: E402

PROVIDER = "lab_workbench01"
ASSEMBLY = "fragment/assembly/assembly/lab_workbench01/assembly_assembly_lab_workbench01.usda"
ENVELOPE_CM = 1.0
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
    ifaces = write_interfaces(ex, str(out / "iface"), envelope=ENVELOPE_CM)
    print("   %d placements in %d groups -> %d offers, %d consumer surfaces  (%.0f ms)"
          % (len(ex.placements), len(ex.groups), len(ex.placements), len(ex.assets),
             (time.perf_counter() - t0) * 1000))
    for g in ex.groups:
        n = sum(1 for p in ex.placements if p.group == g)
        print("   %-18s %3d mounts" % (g, n))

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

    step("republish workbench: %s raised 0.5 cm (inside the %.0f cm envelope)"
         % (GATE_GROUP, ENVELOPE_CM))
    ok_iface = out / "iface" / ("%s.ok.usda" % PROVIDER)
    ok_iface.write_text(provider_interface(ex, envelope=ENVELOPE_CM,
                                           nudge={GATE_GROUP: (0.0, 0.5, 0.0)}))
    repo.save(PROVIDER, A / "entity" / PROVIDER / ("%s.usda" % PROVIDER), "alab",
              "%s +0.5cm" % GATE_GROUP, interface=ok_iface)
    rev, forced = repo.promote(PROVIDER, "@wip", "approved")
    print("   promoted %s -> @approved  (%d violations)" % (rev, len(forced)))

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
        print("   REFUSED: %s %s -> @%s  (%d violations)"
              % (e.asset, e.rev, e.channel, len(e.violations)))
        for v in e.violations[:6]:
            print("     %s" % v)
        if len(e.violations) > 6:
            print("     ... and %d more, every one on %s" % (len(e.violations) - 6, GATE_GROUP))
    print("   @approved still at %s" % repo.ledger.channels(PROVIDER)["approved"])

    step("drift since baseline %s" % b.number)
    pins = repo.resolve(channel="approved")
    now = repo.merkle_root(pins)
    print("   baseline %s   now %s   %s"
          % (b.merkle_root[:16], now[:16],
             "DRIFTED (the +0.5cm republish is on @approved)" if now != b.merkle_root else "same"))

    step("verify")
    v = repo.store.verify()
    stale = repo.stale_generators()
    print("   blobs ok %d  corrupt %d  missing %d   stale generators %d"
          % (len(v["ok"]), len(v["corrupt"]), len(v["missing_chunks"]), len(stale)))
    print("\nworking dir: %s" % out.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
