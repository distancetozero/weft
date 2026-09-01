"""deps -- what depends on what, in USD.

    python -m deps build   ./assets
    python -m deps breaks  ./assets hero_car.usda      # what breaks if I republish this
    python -m deps needs   ./assets shots/sh0120.usda  # the pull closure
    python -m deps why     ./assets a.usda b.usda      # which opinion creates the edge
    python -m deps orphans ./assets                    # edges pointing at nothing
    python -m deps stats   ./assets

`breaks` exits 1 if anything depends on the target, so it can gate a publish.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .graph import Cache, build, discover


def _rel(path: str, root: str) -> str:
    try:
        return os.path.relpath(path, root)
    except ValueError:
        return path


def _load(args, quiet: bool = False):
    paths = discover(args.root)
    if not paths:
        print("deps: no USD layers under %s" % args.root, file=sys.stderr)
        return None, None
    cache = None if args.no_cache else Cache(args.cache or _default_cache(args.root))
    prog = None
    if not quiet and not args.json and len(paths) > 400:
        def prog(i, n):
            if i % 200 == 0 or i == n:
                print("\r  walking %d/%d" % (i, n), end="", file=sys.stderr)
    g = build(paths, cache=cache, progress=prog)
    if prog:
        print("", file=sys.stderr)
    if cache:
        cache.save()
    return g, cache


def _default_cache(root: str) -> str:
    base = root if os.path.isdir(root) else os.path.dirname(root)
    return os.path.join(base, ".deps-cache.json")


def _match(g, root: str, needle: str) -> Optional[str]:
    """Accept a full path, a relative path, or a bare filename."""
    target = os.path.normpath(os.path.abspath(needle))
    if target in g.records:
        return target
    joined = os.path.normpath(os.path.abspath(os.path.join(root, needle)))
    if joined in g.records:
        return joined
    hits = [i for i in g.records if os.path.basename(i) == os.path.basename(needle)]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        print("deps: %r is ambiguous:" % needle, file=sys.stderr)
        for h in sorted(hits):
            print("    %s" % _rel(h, root), file=sys.stderr)
    else:
        print("deps: no layer matching %r" % needle, file=sys.stderr)
    return None


def cmd_build(args) -> int:
    g, cache = _load(args)
    if g is None:
        return 2
    s = g.stats()
    print("%d layers · %d specs · %d edges · %d resolved · built in %.2fs"
          % (s["layers"], s["specs"], s["edges"], s["resolved_edges"],
             g.build_seconds))
    if cache:
        print("cache: %d reused, %d walked" % (cache.hits, cache.misses))
    if g.unreadable:
        print("%d layer%s would not open:"
              % (len(g.unreadable), "" if len(g.unreadable) == 1 else "s"))
        for p in g.unreadable[:args.limit]:
            print("    %s" % _rel(p, args.root))
        if len(g.unreadable) > args.limit:
            print("    … and %d more" % (len(g.unreadable) - args.limit))
    if g.ambiguous:
        print("%d namespace edge%s had several candidate layers and were left "
              "unresolved" % (len(g.ambiguous),
                              "" if len(g.ambiguous) == 1 else "s"))
    if s["unresolved"]:
        print("%d edges point at nothing on disk — see `deps orphans`"
              % s["unresolved"])
    return 0


def cmd_breaks(args) -> int:
    g, _ = _load(args)
    if g is None:
        return 2
    ident = _match(g, args.root, args.layer)
    if ident is None:
        return 2

    direct = g.direct_dependents(ident)
    everything = g.dependents(ident)
    indirect = everything - direct

    if args.json:
        print(json.dumps({
            "layer": _rel(ident, args.root),
            "direct": sorted(_rel(d, args.root) for d in direct),
            "transitive": sorted(_rel(d, args.root) for d in indirect),
            "total": len(everything),
        }, indent=2))
        return 1 if everything else 0

    if not everything:
        print("nothing depends on %s" % _rel(ident, args.root))
        return 0

    print("republishing %s affects %d layer%s"
          % (_rel(ident, args.root), len(everything),
             "" if len(everything) == 1 else "s"))
    print()
    print("DIRECT (%d)" % len(direct))
    for d in sorted(direct):
        edges = g.why(d, ident)
        kinds = sorted({e.kind for e in edges})
        print("  %-52s %s" % (_rel(d, args.root), ",".join(kinds)))
    if indirect:
        print()
        print("THROUGH THOSE (%d)" % len(indirect))
        for d in sorted(indirect)[:args.limit]:
            print("  %s" % _rel(d, args.root))
        if len(indirect) > args.limit:
            print("  … and %d more" % (len(indirect) - args.limit))
    return 1


def cmd_needs(args) -> int:
    g, _ = _load(args)
    if g is None:
        return 2
    ident = _match(g, args.root, args.layer)
    if ident is None:
        return 2

    closure = g.needs(ident, depth=args.depth)
    layers, assets = g.split(closure)

    if args.json:
        print(json.dumps({
            "layer": _rel(ident, args.root),
            "layers": sorted(_rel(d, args.root) for d in layers),
            "assets": sorted(_rel(d, args.root) for d in assets),
            "total_layers": len(layers),
            "total_assets": len(assets),
        }, indent=2))
        return 0

    total_mb = sum(g.records[c].size for c in layers) / 1e6
    print("%s needs %d layer%s (%.1f MB)"
          % (_rel(ident, args.root), len(layers),
             "" if len(layers) == 1 else "s", total_mb))
    if assets:
        print("  plus %d non-layer asset%s (textures, caches)"
              % (len(assets), "" if len(assets) == 1 else "s"))
    print()
    direct = g.direct_needs(ident)
    for d in sorted(layers):
        mark = "*" if d in direct else " "
        print("  %s %s" % (mark, _rel(d, args.root)))
    if assets and args.show_assets:
        print()
        for d in sorted(assets)[:args.limit]:
            print("    %s" % _rel(d, args.root))
        if len(assets) > args.limit:
            print("    … and %d more" % (len(assets) - args.limit))
    print()
    print("* = referenced directly")
    return 0


def cmd_why(args) -> int:
    g, _ = _load(args)
    if g is None:
        return 2
    a = _match(g, args.root, args.src)
    b = _match(g, args.root, args.dst)
    if a is None or b is None:
        return 2

    direct = g.why(a, b)
    if direct:
        print("%s -> %s, directly:" % (_rel(a, args.root), _rel(b, args.root)))
        for e in direct:
            label = "%s.%s" % (e.src_prim, e.name) if e.name else e.src_prim
            print("  %-10s %s" % (e.kind, label))
            print("             -> %s" % e.target)
        return 0

    chain = g.path_between(a, b)
    if not chain:
        print("%s does not depend on %s" % (_rel(a, args.root), _rel(b, args.root)))
        return 1
    print("%s reaches %s in %d hops:"
          % (_rel(a, args.root), _rel(b, args.root), len(chain) - 1))
    for i, node in enumerate(chain):
        print("  %s%s" % ("  " * i, _rel(node, args.root)))
    return 0


def cmd_orphans(args) -> int:
    g, _ = _load(args)
    if g is None:
        return 2
    hooks = [u for u in g.unresolved if u.class_hook]
    rest = [u for u in g.unresolved if not u.class_hook]
    unshadowed = [u for u in rest if not u.shadowable]
    shadowable = [u for u in rest if u.shadowable]

    if args.json:
        print(json.dumps({
            "unshadowed": [{
                "source": _rel(u.source, args.root), "prim": u.src_prim,
                "kind": u.kind, "name": u.name, "target": u.target,
            } for u in unshadowed],
            "shadowable": [{
                "source": _rel(u.source, args.root), "prim": u.src_prim,
                "kind": u.kind, "name": u.name, "target": u.target,
            } for u in shadowable],
            "class_hooks": len(hooks),
        }, indent=2))
        return 1 if unshadowed else 0

    if not g.unresolved:
        print("every edge resolves")
        return 0

    def show(items, header, gloss):
        print(header)
        print(gloss)
        print()
        by_source = {}
        for u in items:
            by_source.setdefault(u.source, []).append(u)
        for src in sorted(by_source)[:args.limit]:
            print("  %s" % _rel(src, args.root))
            for u in by_source[src][:6]:
                label = "%s.%s" % (u.src_prim, u.name) if u.name else u.src_prim
                print("      %-10s %s -> %s" % (u.kind, label, u.target))
            if len(by_source[src]) > 6:
                print("      … and %d more" % (len(by_source[src]) - 6))
        if len(by_source) > args.limit:
            print("  … and %d more layers" % (len(by_source) - args.limit))

    if unshadowed:
        show(unshadowed,
             "DANGLING (%d) — in layers nothing references" % len(unshadowed),
             "  Nothing sits above these to override them. Most likely dead.")
    if shadowable:
        if unshadowed:
            print()
        show(shadowable,
             "UNRESOLVED IN ISOLATION (%d)" % len(shadowable),
             "  These layers are referenced by others, and a parent may already\n"
             "  override the edge — a DCC-exported geo layer binding to a path\n"
             "  its asset layer re-points is normal. Verify on a composed stage\n"
             "  before acting.")
    if hooks:
        print()
        print("Ignored %d inherit%s to an undefined class -- the standard USD "
              "hook idiom,\nnot a broken edge."
              % (len(hooks), "" if len(hooks) == 1 else "s"))
    return 1 if unshadowed else 0


def cmd_stats(args) -> int:
    g, cache = _load(args)
    if g is None:
        return 2
    s = g.stats()
    roots, leaves = g.roots(), g.leaves()

    fan = sorted(((len(v), k) for k, v in g.reverse.items()), reverse=True)
    if args.json:
        print(json.dumps({
            "stats": s, "build_seconds": round(g.build_seconds, 3),
            "roots": [_rel(r, args.root) for r in roots[:20]],
            "most_depended_on": [
                {"layer": _rel(k, args.root), "dependents": n} for n, k in fan[:20]],
        }, indent=2))
        return 0

    print("layers          %d" % s["layers"])
    print("prim specs      %d" % s["specs"])
    print("edges           %d authored, %d resolved" % (s["edges"], s["resolved_edges"]))
    print("unresolved      %d" % s["unresolved"])
    print("roots           %d (nothing references these)" % len(roots))
    print("leaves          %d (these reference nothing)" % len(leaves))
    print("build           %.2fs" % g.build_seconds)
    if fan:
        print()
        print("MOST DEPENDED ON")
        for n, k in fan[:10]:
            print("  %4d  %s" % (n, _rel(k, args.root)))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="deps",
        description="What depends on what, in USD, without opening a scene.")
    ap.add_argument("--cache", help="path to the graph cache")
    ap.add_argument("--no-cache", action="store_true", help="always re-walk")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--limit", type=int, default=40, help="cap long listings")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("build", help="walk a tree and cache the graph")
    p.add_argument("root")
    p.set_defaults(fn=cmd_build)

    p = sub.add_parser("breaks", help="what breaks if I republish this")
    p.add_argument("root"); p.add_argument("layer")
    p.set_defaults(fn=cmd_breaks)

    p = sub.add_parser("needs", help="everything this layer depends on")
    p.add_argument("root"); p.add_argument("layer")
    p.add_argument("--depth", type=int, default=None, help="stop after N hops")
    p.add_argument("--show-assets", action="store_true",
                   help="also list textures and caches, not just layers")
    p.set_defaults(fn=cmd_needs)

    p = sub.add_parser("why", help="which opinion creates a dependency")
    p.add_argument("root"); p.add_argument("src"); p.add_argument("dst")
    p.set_defaults(fn=cmd_why)

    p = sub.add_parser("orphans", help="edges pointing at nothing on disk")
    p.add_argument("root")
    p.set_defaults(fn=cmd_orphans)

    p = sub.add_parser("stats", help="shape of the graph")
    p.add_argument("root")
    p.set_defaults(fn=cmd_stats)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
