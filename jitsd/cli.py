"""The rung 1 command surface."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import List, Optional

from .contracts import Surface
from .store import CorruptObject
from .ledger import BreakingChange, ChannelRaced, Repo
from . import generators as _gens
from . import query as _query
from .generators import vehicle as _vehicle  # noqa: F401  registers the built-ins
from . import slice as _slice


def _human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return "%.0f %s" % (n, unit) if unit == "B" else "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f TiB" % n


def _author() -> str:
    return os.environ.get("JITSD_AUTHOR") or getpass.getuser()


# -- commands -------------------------------------------------------------

def cmd_init(args) -> int:
    repo = Repo(Path(args.path))
    if repo.exists():
        print("already a jitsd repository: %s" % repo.dir)
        return 0
    repo.init()
    print("initialised empty jitsd repository in %s" % repo.dir)
    return 0


def cmd_save(args) -> int:
    repo = Repo.find()
    src = Path(args.file)
    if not src.is_file():
        print("no such file: %s" % src, file=sys.stderr)
        return 1
    iface = Path(args.interface) if args.interface else None
    if iface and not iface.is_file():
        print("no such interface file: %s" % iface, file=sys.stderr)
        return 1
    before = repo.store.stats()
    rev = repo.save(args.asset, src, _author(), args.message or "", interface=iface)
    after = repo.store.stats()
    added = after.physical_bytes - before.physical_bytes
    print("%s %s  %s  (+%s on disk)" % (args.asset, rev.rev, _human(rev.size), _human(added)))
    if rev.message:
        print("  %s" % rev.message)
    surf = Surface.from_dict(rev.surface)
    if surf:
        print("  contract surface: %d offered, %d required"
              % (len(surf.offers), len(surf.requires)))
    return 0


def cmd_log(args) -> int:
    repo = Repo.find()
    revs = repo.ledger.revisions(args.asset)
    if not revs:
        print("no revisions for %s" % args.asset)
        return 0
    chans = repo.ledger.channels(args.asset)
    at = {}
    for name, rev in chans.items():
        at.setdefault(rev, []).append(name)
    for rev in reversed(revs):
        r = repo.ledger.read_revision(args.asset, rev)
        tags = ("  <- " + ", ".join("@" + c for c in sorted(at[rev]))) if rev in at else ""
        print("%s  %s  %-9s %s%s" % (r.rev, r.created, _human(r.size), r.author, tags))
        if r.message:
            print("        %s" % r.message)
    return 0


def cmd_channels(args) -> int:
    repo = Repo.find()
    assets = [args.asset] if args.asset else repo.ledger.asset_names()
    if not assets:
        print("no assets yet")
        return 0
    for a in assets:
        chans = repo.ledger.channels(a)
        if not chans:
            continue
        print(a)
        for name, rev in chans.items():
            print("  @%-10s %s" % (name, rev))
    return 0


def cmd_promote(args) -> int:
    repo = Repo.find()
    try:
        rev, forced = repo.promote(args.asset, args.rev, args.to, force=args.force)
    except BreakingChange as e:
        print("REFUSED: %s %s -> @%s is a breaking change" % (e.asset, e.rev, e.channel),
              file=sys.stderr)
        for v in e.violations:
            print("  %s" % v, file=sys.stderr)
        print("\nBump the contract major, or --force to promote anyway.", file=sys.stderr)
        return 1
    except ChannelRaced as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    # The violations are the ones measured BEFORE the pointer moved. Re-checking
    # afterwards always returns empty -- the channel now holds the revision it
    # was compared against -- so a forced breaking promotion printed as clean.
    note = ""
    if forced:
        note = "  (forced over %d violation%s)" % (
            len(forced), "" if len(forced) == 1 else "s")
    print("@%s -> %s %s%s" % (args.to, args.asset, rev, note))
    for v in forced:
        print("  %s" % v, file=sys.stderr)
    return 0


def cmd_declare(args) -> int:
    """Create a generator-backed revision: an asset that is a function."""
    repo = Repo.find()
    params = {}
    for kv in args.param or []:
        if "=" not in kv:
            print("--param expects k=v, got %r" % kv, file=sys.stderr)
            return 1
        k, _, v = kv.partition("=")
        params[k.strip()] = v.strip()
    try:
        rev = repo.declare(args.asset, args.generator, params, _author(), args.message or "")
    except (KeyError, ValueError) as e:
        print("%s" % e, file=sys.stderr)
        return 1
    surf = Surface.from_dict(rev.surface)
    print("%s %s  generator %s" % (args.asset, rev.rev, rev.generator))
    print("  params: %s" % ", ".join("%s=%g" % kv for kv in sorted((rev.params or {}).items())))
    print("  computed surface: %d offered, %d required" % (len(surf.offers), len(surf.requires)))
    return 0


def cmd_generators(args) -> int:
    for ident in _gens.known():
        g = _gens.get(ident)
        ps = ", ".join("%s=%g%s" % (p.name, p.default, p.unit) for p in g.params)
        print("%-18s %-9s %s" % (ident, g.cost_class, ps))
        if g.variation_points:
            print("%-18s %-9s variation points: %s"
                  % ("", "", ", ".join(g.variation_points)))
    return 0


def cmd_compile(args) -> int:
    """Compile a query document into a stage, on demand."""
    repo = Repo.find()
    try:
        q = _query.parse_query_file(Path(args.query))
        c = _query.compile_query(repo, q, context=args.context,
                                 geometry=not args.resolve_only)
    except (KeyError, ValueError) as e:
        print("%s" % e, file=sys.stderr)
        return 1

    for d in c.resolution.diagnostics:
        print("  %s" % d, file=sys.stderr if d.severity == "error" else sys.stdout)
    if not c.ok:
        print("resolution failed; nothing compiled", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(c.stage)

    where = args.out or "(not written)"
    print("%s  context %s  baseline %s" % (where, c.context.name, c.pins and (q.baseline or "floating")))
    print("  bindings   %d" % len(c.resolution.bindings))
    if c.scene_bounds:
        lo, hi = c.scene_bounds
        print("  bounds     (%.3g, %.3g, %.3g) .. (%.3g, %.3g, %.3g)" % (lo + hi))
    print("  phase A    %7.2f ms   relational -- parameters, contracts, bounds" % c.phase_a_ms)
    print("  phase B    %7.2f ms   materialise -- geometry" % c.phase_b_ms)
    print("  digest     sha256:%s" % c.digest[:16])
    return 0


def _parse_overlay(raw, default_author):
    """--pin / --omit take "asset: reason"."""
    asset, _, reason = raw.partition(":")
    return _slice.Overlay(asset=asset.strip(), author=default_author,
                          reason=reason.strip() or "(no reason given)")


def cmd_select(args) -> int:
    """Resolve a slice and print its receipt. Nothing materialises."""
    repo = Repo.find()
    if args.from_file:
        spec = _slice.read_spec(Path(args.from_file))
        spec.seeds += args.seeds or []
    else:
        spec = _slice.SliceSpec(seeds=args.seeds or [])

    # Precedence: an explicit flag > the rule set > the spec's own defaults.
    given = {
        "closure": ([] if args.closure == "none" else args.closure.split(","))
                   if args.closure is not None else None,
        "follow": args.follow.split(",") if args.follow else None,
        "depth": args.depth,
        "include_optional": True if args.include_optional else None,
        "view": args.view.split(",") if args.view else None,
        "context": args.context,
    }
    if args.rules:
        try:
            rules, applied = _slice.load_rules(repo, args.rules)
        except (KeyError, ValueError) as e:
            print("rules: %s" % e, file=sys.stderr)
            return 1
        rules.apply(spec, given)
        spec.rules = applied
    for name, value in given.items():
        if value is not None:
            setattr(spec, name, value)
    spec.baseline = args.baseline or spec.baseline
    spec.channel = args.channel
    if args.label:
        spec.label = args.label
    author = _author()
    spec.pins += [_parse_overlay(x, author) for x in (args.pin or [])]
    spec.omits += [_parse_overlay(x, author) for x in (args.omit or [])]

    try:
        result = _slice.resolve_slice(repo, spec)
    except (KeyError, ValueError) as e:
        print("%s" % e, file=sys.stderr)
        return 1

    print(_slice.receipt(result))

    if args.save_rules:
        rs = _slice.RuleSet.from_spec(spec, author=author, note=args.message or "")
        rev = _slice.save_rules(repo, args.save_rules, rs, author, args.message or "")
        print("\nrules saved: %s %s  (promote to share; apply with --rules %s)"
              % (args.save_rules, rev, args.save_rules))

    if args.impact:
        # The blast-radius display from docs/10-slices.md: what a candidate
        # revision would break, split by whether the consumer is in this slice.
        asset, _, ref = args.impact.partition("@")
        ref = ref or "@wip"
        try:
            rev = repo.ledger.resolve_ref(asset, ref)
        except KeyError as e:
            print("%s" % e, file=sys.stderr)
            return 1
        re = repo.reevaluate(asset, rev, channel=spec.channel, view=spec.view or None)
        members = {m.asset for m in result.members}
        inside = sorted(c for c in re.changed if c in members)
        outside = sorted(c for c in re.changed if c not in members)
        print()
        print("impact of %s %s: %d consumer%s re-evaluated, %d affected"
              % (asset, rev, len(re.consumers), "" if len(re.consumers) == 1 else "s",
                 len(re.changed)))
        print("  inside this slice  (%d): %s" % (len(inside), ", ".join(inside) or "-"))
        print("  outside this slice (%d): %s" % (len(outside), ", ".join(outside) or "-"))
        for v in re.breaking[:8]:
            print("    %s" % v)
        if len(re.breaking) > 8:
            print("    ... and %d more" % (len(re.breaking) - 8))

    if args.out:
        Path(args.out).write_text(_slice.emit_query_document(result))
        print("\nwritten: %s  (a query document -- `jitsd compile` materialises it)"
              % args.out)
    return 0 if result.ok else 1


def cmd_bind(args) -> int:
    """Resolve requirements to offers by contract identity."""
    repo = Repo.find()
    res = repo.bind(baseline=args.baseline, channel=args.channel)
    surfaces = repo.surfaces(repo.resolve(baseline=args.baseline, channel=args.channel))

    if not surfaces:
        print("no asset declares a contract surface")
        return 0

    noffers = sum(len(s.offers) for s in surfaces.values())
    nreq = sum(len(s.requires) for s in surfaces.values())
    print("%d asset%s  ·  %d offered  ·  %d required"
          % (len(surfaces), "" if len(surfaces) == 1 else "s", noffers, nreq))
    print()

    for b in res.bindings:
        who = "%s %s" % (b.consumer, b.requirement.rsplit(":", 1)[-1])
        print("  %-30s %-12s -> %s" % (who, b.contract, ", ".join(b.providers)))

    if res.diagnostics:
        print()
        for d in res.diagnostics:
            stream = sys.stderr if d.severity == "error" else sys.stdout
            print("  %s" % d, file=stream)

    return 0 if res.ok else 1


def _context_file(raw: str) -> str:
    """A raw USD file path, or a ledger asset name resolved via the repo."""
    if os.path.exists(raw):
        return raw
    repo = Repo.find()
    rev = repo.ledger.resolve_ref(raw, "approved")
    r = repo.ledger.read_revision(raw, rev)
    if r.blob is None:
        raise ValueError("context %s@%s is generator-backed; materialise it with jitsd checkout first"
                         % (raw, rev))
    import tempfile
    out = Path(tempfile.mkdtemp(prefix="jitsd-ctx-")) / ("%s.usda" % raw)
    repo.store.checkout(r.blob, out)
    return str(out)


def cmd_pull(args) -> int:
    from . import manifest as _manifest
    from . import pull as _pull
    from .registry import parse_extractors

    if args.verify:
        findings = _manifest.verify(Path(args.verify).read_text())
        for f in findings:
            print("  ! %s" % f)
        print("verify: %s" % ("ok" if not findings else "%d findings" % len(findings)))
        return 0 if not findings else 1

    if not args.context:
        print("pull: --context FILE_OR_ASSET is required", file=sys.stderr)
        return 1
    extractors = []
    if args.extractors:
        extractors = parse_extractors(Path(args.extractors).read_text())
    try:
        ctx = _context_file(args.context)
    except (ValueError, KeyError) as e:
        print("pull: %s" % e, file=sys.stderr)
        return 1
    p = _pull.pull(ctx, args.seeds, follow=args.follow, depth=args.depth,
                   extractors=extractors)
    _manifest.layer_hashes(p)

    for r in p.resolutions:
        line = "seed %s -> %d (%s" % (r.seed.raw, r.matched, r.mode)
        if r.complement:
            line += ", %d do not author the key" % r.complement
        line += ")"
        if r.note:
            line += "  %s" % r.note
        print(line)
    print("members (%d):" % len(p.members))
    for m in p.members:
        via = "seed" if m.via_kind == "seed" else "%s <- %s" % (m.via_kind, m.from_member)
        print("  %-44s %s" % (m.path, via))
    if p.boundary:
        print("boundary (%d):" % len(p.boundary))
        for b in p.boundary:
            print("  %-44s %-24s %s [%s]" % (b.target, b.kind, b.reason, b.omission))
    for d in p.declarations:
        print("  ~ %s" % d)
    print("fitness: %s" % p.fitness.get("statement", ""))

    doc = _manifest.to_document(p)
    findings = _manifest.verify(doc)
    for f in findings:
        print("  ! %s" % f, file=sys.stderr)
    if args.out:
        Path(args.out).write_text(doc)
        print("manifest: %s" % args.out)
    if args.mask_out:
        _manifest.write_mask(p, args.mask_out)
        print('mask: %s  (usdrecord --mask "$(cat %s | tr \'\\n\' \',\')" ...)'
              % (args.mask_out, args.mask_out))
    return 0 if not findings else 1


def cmd_who(args) -> int:
    from . import pull as _pull
    try:
        ctx = _context_file(args.context)
    except (ValueError, KeyError) as e:
        print("who: %s" % e, file=sys.stderr)
        return 1
    kinds = args.kinds.split(",") if args.kinds else None
    for src, kind, member in _pull.who(ctx, args.seeds, kinds=kinds):
        print("  %-44s %-24s -> %s" % (src, kind, member))
    return 0


def cmd_check(args) -> int:
    """What would promoting this revision break?"""
    repo = Repo.find()
    violations = repo.check_promotion(args.asset, args.rev, args.to)
    rev = repo.ledger.resolve_ref(args.asset, args.rev)
    if not violations:
        print("%s %s -> @%s: compatible" % (args.asset, rev, args.to))
        return 0
    print("%s %s -> @%s: breaking" % (args.asset, rev, args.to))
    for v in violations:
        print("  %s" % v)
    return 1


def cmd_back(args) -> int:
    repo = Repo.find()
    rev = repo.ledger.resolve_ref(args.asset, args.rev)
    repo.ledger.set_channel(args.asset, "wip", rev)
    print("@wip -> %s %s  (pointer move, no data copied)" % (args.asset, rev))
    return 0


def cmd_checkout(args) -> int:
    repo = Repo.find()
    rev = repo.ledger.resolve_ref(args.asset, args.rev)
    r = repo.ledger.read_revision(args.asset, rev)
    if r.blob is None:
        print("%s %s is generator-backed (%s); there is no stored payload to "
              "check out.\nUse `jitsd compile` to materialise it."
              % (args.asset, rev, r.generator), file=sys.stderr)
        return 1
    try:
        repo.store.checkout(r.blob, Path(args.dest))
    except CorruptObject as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        print("Nothing was written. Run `jitsd verify` to survey the store.",
              file=sys.stderr)
        return 1
    except KeyError as e:
        print("REFUSED: %s" % e, file=sys.stderr)
        return 1
    print("%s %s -> %s  (%s)" % (args.asset, rev, args.dest, _human(r.size)))
    return 0


def cmd_baseline(args) -> int:
    repo = Repo.find()
    if args.baseline_cmd == "cut":
        b = repo.cut_baseline(label=args.label or "", cut_by=_author(),
                              channel=args.channel)
        name = b.label or "(unlabelled)"
        print("baseline %s  %s" % (b.number, name))
        print("  merkle sha256:%s" % b.merkle_root[:16])
        for asset, rev in sorted(b.pins.items()):
            print("  %-24s %s" % (asset, rev))
        return 0

    nums = repo.ledger.baseline_numbers()
    if not nums:
        print("no baselines cut yet")
        return 0
    for n in nums:
        b = repo.ledger.read_baseline(n)
        print("%s  %s  %-22s %d pinned  sha256:%s"
              % (b.number, b.cut, b.label or "-", len(b.pins), b.merkle_root[:12]))
    return 0


def cmd_resolve(args) -> int:
    repo = Repo.find()
    pins = repo.resolve(baseline=args.baseline, channel=args.channel)
    minted: Optional[str] = None
    if not args.baseline:
        # You never ask for a baseline -- you receive one.
        b = repo.cut_baseline(label=args.label or "", cut_by="resolve",
                              channel=args.channel)
        minted = b.number
        pins = b.pins
    root = repo.merkle_root(pins)
    lock = {
        "baseline": args.baseline or minted,
        "minted": minted is not None,
        "merkleRoot": "sha256:" + root,
        "pins": pins,
    }
    Path(args.out).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")
    print("resolved against baseline %s%s -> %s"
          % (lock["baseline"], " (minted)" if minted else "", args.out))
    for asset, rev in sorted(pins.items()):
        print("  %-24s %s" % (asset, rev))
    return 0


def cmd_drift(args) -> int:
    """Has anything changed since this baseline? One hash comparison."""
    repo = Repo.find()
    b = repo.ledger.read_baseline(args.baseline)
    now = repo.resolve(channel=args.channel)
    now_root = repo.merkle_root(now)
    if now_root == b.merkle_root:
        print("no drift since baseline %s (%s)" % (b.number, b.label or "-"))
        return 0
    print("DRIFT since baseline %s (%s)" % (b.number, b.label or "-"))
    for asset in sorted(set(b.pins) | set(now)):
        was, isnow = b.pins.get(asset), now.get(asset)
        if was != isnow:
            print("  %-24s %s -> %s" % (asset, was or "(absent)", isnow or "(absent)"))
    return 1


def cmd_diff(args) -> int:
    repo = Repo.find()
    a = repo.ledger.read_revision(args.asset, repo.ledger.resolve_ref(args.asset, args.a))
    b = repo.ledger.read_revision(args.asset, repo.ledger.resolve_ref(args.asset, args.b))

    # A generator-backed revision has no blob, so comparing blobs calls every
    # pair identical -- including two declarations with different parameters,
    # which describe different geometry. Compare what actually defines them.
    if a.blob is None or b.blob is None:
        same_gen = (a.generator == b.generator
                    and a.generator_hash == b.generator_hash)
        if same_gen and (a.params or {}) == (b.params or {}):
            print("%s %s == %s  (same generator and parameters)"
                  % (args.asset, a.rev, b.rev))
            return 0
        print("%s %s -> %s" % (args.asset, a.rev, b.rev))
        if a.generator != b.generator:
            print("  generator  %s -> %s" % (a.generator, b.generator))
        elif a.generator_hash != b.generator_hash:
            print("  generator  %s (code changed)" % a.generator)
        pa, pb = a.params or {}, b.params or {}
        for k in sorted(set(pa) | set(pb)):
            if pa.get(k) != pb.get(k):
                print("  %-10s %s -> %s" % (k, pa.get(k, "(unset)"), pb.get(k, "(unset)")))
        return 0

    if a.blob == b.blob:
        print("%s %s == %s  (identical payload)" % (args.asset, a.rev, b.rev))
        return 0
    ca = repo.store.manifest(a.blob)["chunks"]
    cb = repo.store.manifest(b.blob)["chunks"]
    sa, sb = set(ca), set(cb)
    shared = sa & sb
    changed = sum(len(repo.store._chunk_path(c).read_bytes()) for c in (sb - sa))
    print("%s %s -> %s" % (args.asset, a.rev, b.rev))
    print("  size     %s -> %s" % (_human(a.size), _human(b.size)))
    print("  chunks   %d -> %d   shared %d   new %d" % (len(ca), len(cb), len(shared), len(sb - sa)))
    print("  changed  %s of %s (%.1f%%)"
          % (_human(changed), _human(b.size), 100.0 * changed / b.size if b.size else 0))
    return 0


def cmd_stat(args) -> int:
    repo = Repo.find()
    st = repo.store.stats()
    nrev = sum(len(repo.ledger.revisions(a)) for a in repo.ledger.asset_names())
    print("assets     %d" % len(repo.ledger.asset_names()))
    print("revisions  %d" % nrev)
    print("baselines  %d" % len(repo.ledger.baseline_numbers()))
    print("blobs      %d" % st.blobs)
    print("chunks     %d" % st.chunks)
    print("logical    %s   (what the versions would cost as separate files)" % _human(st.logical_bytes))
    print("physical   %s   (what is actually on disk)" % _human(st.physical_bytes))
    print("dedup      %.2fx" % st.ratio)
    return 0


def cmd_gc(args) -> int:
    repo = Repo.find()
    keep = repo.reachable_blobs(prune_history=args.prune_history)
    if args.dry_run:
        st = repo.store.stats()
        print("would keep %d of %d blobs" % (len(keep), st.blobs))
        return 0
    res = repo.store.gc(keep)
    print("dropped %d blobs, %d chunks, freed %s"
          % (res["blobs"], res["chunks"], _human(res["bytes"])))
    return 0


def cmd_verify(args) -> int:
    """Re-hash every stored blob, and check every pinned generator.

    A content-addressed store can prove its own integrity for the cost of one
    hash per blob. Nothing else in the system will notice a flipped byte.
    """
    repo = Repo.find()
    res = repo.store.verify()
    ok, corrupt, missing = res["ok"], res["corrupt"], res["missing_chunks"]
    print("blobs      %d ok" % len(ok))
    for bid in corrupt:
        print("  CORRUPT        %s  (bytes do not match the id)" % bid[:16], file=sys.stderr)
    for bid in missing:
        print("  MISSING CHUNK  %s" % bid[:16], file=sys.stderr)

    stale = repo.stale_generators()
    if stale:
        print("generators %d stale" % len(stale))
        for s in stale:
            print("  %s %s  %s: %s" % (s["asset"], s["rev"], s["generator"], s["why"]),
                  file=sys.stderr)
    else:
        print("generators all match their recorded code hash")

    return 1 if (corrupt or missing or stale) else 0


# -- parser ---------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jitsd", description="JIT-SD rung 1: solo, offline, no contracts.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a repository here")
    s.add_argument("path", nargs="?", default=".")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("save", help="store a file as a new revision and move @wip")
    s.add_argument("asset")
    s.add_argument("file")
    s.add_argument("-m", "--message", default="")
    s.add_argument("--interface", help="authored .usda declaring this asset's contract surface")
    s.set_defaults(fn=cmd_save)

    s = sub.add_parser("log", help="revision history for an asset")
    s.add_argument("asset")
    s.set_defaults(fn=cmd_log)

    s = sub.add_parser("channels", help="show channel pointers")
    s.add_argument("asset", nargs="?")
    s.set_defaults(fn=cmd_channels)

    s = sub.add_parser("promote", help="move a channel pointer to a revision")
    s.add_argument("asset")
    s.add_argument("rev")
    s.add_argument("--to", required=True)
    s.add_argument("--force", action="store_true", help="promote over a breaking change")
    s.set_defaults(fn=cmd_promote)

    s = sub.add_parser("declare", help="create a generator-backed revision")
    s.add_argument("asset")
    s.add_argument("--generator", required=True)
    s.add_argument("--param", action="append", metavar="K=V")
    s.add_argument("-m", "--message", default="")
    s.set_defaults(fn=cmd_declare)

    s = sub.add_parser("generators", help="list registered generators")
    s.set_defaults(fn=cmd_generators)

    s = sub.add_parser("compile", help="compile a query document into a stage")
    s.add_argument("query")
    s.add_argument("--context", default=None)
    s.add_argument("-o", "--out")
    s.add_argument("--resolve-only", action="store_true",
                   help="phase A only: contracts and bounds, no geometry")
    s.set_defaults(fn=cmd_compile)

    s = sub.add_parser("select", help="resolve a slice and print its receipt")
    s.add_argument("seeds", nargs="*",
                   help="name/glob, provides:C@N, requires:C@N, role:R, "
                        "author:A, changed-since:BASELINE, box:x0,y0,z0,x1,y1,z1")
    s.add_argument("--closure", default=None, help="needs | feeds | needs,feeds | none")
    s.add_argument("--follow", default=None, metavar="KINDS",
                   help="relationship kinds closure may follow, e.g. Mount,usd:binding "
                        "(contract names or usd:arc|binding|rel|conn|inherit|collection|asset); "
                        "default: all")
    s.add_argument("--view", default=None, metavar="ATTRS",
                   help="binding attributes in view for --impact, e.g. position,material")
    s.add_argument("--rules", default=None, metavar="NAME[@REF]",
                   help="apply a saved rule set; explicit flags still win")
    s.add_argument("--save-rules", default=None, metavar="NAME",
                   help="save this slice's rules (not its seeds) as an asset revision")
    s.add_argument("-m", "--message", default=None, help="note for --save-rules")
    s.add_argument("--depth", type=int, default=None)
    s.add_argument("--include-optional", action="store_true",
                   help="pull substitutable/omittable providers instead of listing them as boundary")
    s.add_argument("--pin", action="append", metavar='"ASSET: reason"')
    s.add_argument("--omit", action="append", metavar='"ASSET: reason"')
    s.add_argument("--baseline")
    s.add_argument("--channel", default="approved")
    s.add_argument("--context", default=None)
    s.add_argument("--label", default="")
    s.add_argument("--from", dest="from_file", help="reload a slice from an emitted query document")
    s.add_argument("-o", "--out", help="emit the slice as a query document")
    s.add_argument("--impact", metavar="ASSET[@REV]",
                   help="what promoting this candidate would break, inside and "
                        "outside the slice (default REV: @wip)")
    s.set_defaults(fn=cmd_select)

    s = sub.add_parser("bind", help="resolve requirements to offers by contract")
    s.add_argument("--baseline")
    s.add_argument("--channel", default="approved")
    s.set_defaults(fn=cmd_bind)

    s = sub.add_parser("check", help="would promoting this revision break anything?")
    s.add_argument("asset")
    s.add_argument("rev")
    s.add_argument("--to", default="approved")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("back", help="point @wip at an earlier revision")
    s.add_argument("asset")
    s.add_argument("rev")
    s.set_defaults(fn=cmd_back)

    s = sub.add_parser("checkout", help="materialise a revision to a file")
    s.add_argument("asset")
    s.add_argument("rev")
    s.add_argument("dest")
    s.set_defaults(fn=cmd_checkout)

    s = sub.add_parser("baseline", help="cut or list baselines")
    s.add_argument("baseline_cmd", nargs="?", default="list", choices=["cut", "list"])
    s.add_argument("--label", default="")
    s.add_argument("--channel", default="approved")
    s.set_defaults(fn=cmd_baseline)

    s = sub.add_parser("resolve", help="pin the world and write a lock")
    s.add_argument("--baseline")
    s.add_argument("--channel", default="approved")
    s.add_argument("--label", default="")
    s.add_argument("--out", default="jitsd.lock")
    s.set_defaults(fn=cmd_resolve)

    s = sub.add_parser("drift", help="has anything changed since a baseline?")
    s.add_argument("baseline")
    s.add_argument("--channel", default="approved")
    s.set_defaults(fn=cmd_drift)

    s = sub.add_parser("diff", help="structural diff between two revisions")
    s.add_argument("asset")
    s.add_argument("a")
    s.add_argument("b")
    s.set_defaults(fn=cmd_diff)

    s = sub.add_parser("stat", help="storage and dedup statistics")
    s.set_defaults(fn=cmd_stat)

    s = sub.add_parser("gc", help="drop unreachable blobs and chunks")
    s.add_argument("--dry-run", action="store_true")
    s.add_argument("--prune-history", action="store_true",
                   help="also collect revisions no channel or baseline points "
                        "at -- this DELETES history that `log` still lists")
    s.set_defaults(fn=cmd_gc)

    s = sub.add_parser("verify", help="check stored bytes against their hashes")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("pull", help="prim-level pull: seeds -> manifest + mask")
    s.add_argument("seeds", nargs="*",
                   help="glob, name:, id:, id:occ:, role:, offers:, requires:, "
                        "where:attr=value, near:SEED,R, within:6-floats, path:")
    s.add_argument("--context", default=None, metavar="FILE_OR_ASSET")
    s.add_argument("--follow", default=None, metavar="TERMS",
                   help="direction-qualified kinds: Mount, up:electrical:feeds*8")
    s.add_argument("--depth", type=int, default=4)
    s.add_argument("--extractors", default=None, metavar="FILE",
                   help="a jitsd__extractors document")
    s.add_argument("-o", "--out", default=None, help="write the manifest here")
    s.add_argument("--mask-out", default=None, help="write member paths, one per line")
    s.add_argument("--verify", default=None, metavar="MANIFEST",
                   help="verify an existing manifest instead of pulling")
    s.set_defaults(fn=cmd_pull)

    s = sub.add_parser("who", help="what depends on this prim (incoming edges)")
    s.add_argument("seeds", nargs="+")
    s.add_argument("--context", required=True, metavar="FILE_OR_ASSET")
    s.add_argument("--kinds", default=None)
    s.set_defaults(fn=cmd_who)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.fn(args)
