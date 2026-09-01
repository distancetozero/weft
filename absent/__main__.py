"""absent -- report what a USD stage refers to that is no longer there.

    python -m absent shot.usda
    python -m absent shot.usda --json
    python -m absent shot.usda --anchor-key "jitsd:id"

Exits 1 if anything is dead, so it can gate a publish.
"""

from __future__ import annotations

import argparse
import json
import sys

from .detect import ANCHOR_KEY, DEAD, MOVED, UNKNOWN, scan_file


def _render(report, show_unknown: bool) -> str:
    out = []
    groups = [
        (DEAD, report.dead, "gone -- nothing defines this any more"),
        (MOVED, report.moved, "the anchor still exists, at a new path"),
    ]
    if show_unknown:
        groups.append(
            (UNKNOWN, report.unknown,
             "refers to nothing, and nothing was recorded to say why"))

    for label, items, gloss in groups:
        if not items:
            continue
        out.append("")
        out.append("%s  (%d)  -- %s" % (label.upper(), len(items), gloss))
        out.append("-" * 72)
        for f in items:
            out.append(str(f))

    out.append("")
    out.append("-" * 72)
    out.append("scanned %d prims, %d prim specs, %d anchors"
               % (report.prims_scanned, report.specs_scanned, report.anchors_found))
    out.append("dead %d   moved %d   unknown %d"
               % (len(report.dead), len(report.moved), len(report.unknown)))

    if report.anchors_found == 0 and (report.unknown or report.dead):
        out.append("")
        out.append("No anchor names on this stage, so every absence reads as "
                   "'unknown'.")
        out.append("Anchors let this tool separate 'gone' from 'moved' -- see "
                   "--anchor-key.")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="absent",
        description="Find what a USD stage refers to that is no longer there.")
    ap.add_argument("stage", help="a .usd / .usda / .usdc file")
    ap.add_argument("--anchor-key", default=ANCHOR_KEY,
                    help="prim custom-data key holding the stable anchor name "
                         "(default: %(default)s)")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit findings as JSON")
    ap.add_argument("--quiet-unknown", action="store_true",
                    help="hide findings where nothing was recorded to explain them")
    args = ap.parse_args(argv)

    try:
        report = scan_file(args.stage, args.anchor_key)
    except IOError as e:
        print("absent: %s" % e, file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps({
            "stage": args.stage,
            "scanned": {
                "prims": report.prims_scanned,
                "prim_specs": report.specs_scanned,
                "anchors": report.anchors_found,
            },
            "findings": [
                {
                    "kind": f.kind, "path": f.path, "detail": f.detail,
                    "verdict": f.verdict, "layer": f.layer, "moved_to": f.moved_to,
                }
                for f in report.findings
            ],
        }, indent=2))
    else:
        print(_render(report, not args.quiet_unknown))

    return 1 if report.dead else 0


if __name__ == "__main__":
    sys.exit(main())
