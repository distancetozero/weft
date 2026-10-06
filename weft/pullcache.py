"""A cross-call cache for pull results, so a repeated pull of the same
expression against an unchanged context skips the whole cost: no stage open, no
seed resolution, no closure walk. On an ALab one-asset pull ~94% of the time is
USD's LoadNone stage-open, which nothing *within* a single pull can avoid -- a
cache is the only lever, exactly as the benchmark concluded.

Freshness is checked by FILE STAT (mtime+size) of the layers the pull actually
consulted, NOT by content hash: hashing a multi-GB layer set is slower than
just opening the stage, so a hash-keyed cache would be pointless here.
Cryptographic hashing stays in the certification manifest, where correctness,
not speed, is the goal. A changed layer changes its (mtime,size) -> the entry is
stale -> recompute; so the cache is self-invalidating on any real edit.

Entries are JSON under $WEFT_CACHE (default ~/.cache/weft/pull), keyed by a hash
of (context path, canonical expression, USD version). Pure stdlib; the Pull
dataclasses are imported lazily to avoid an import cycle with pull.py.
"""
from __future__ import annotations

import hashlib
import json
import os
from typing import List, Optional, Tuple


def _cache_dir() -> str:
    d = os.environ.get("WEFT_CACHE")
    if not d:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
        d = os.path.join(base, "weft", "pull")
    os.makedirs(d, exist_ok=True)
    return d


def _expr(seeds, follow, depth, extractors) -> str:
    follow_s = follow if isinstance(follow, str) else ",".join(follow or [])
    ex = ",".join(sorted(str(e) for e in (extractors or ())))
    return "\x1f".join(["|".join(sorted(seeds)), follow_s, str(depth), ex])


def key(context_file: str, seeds, follow, depth, extractors, usd_version: str) -> str:
    raw = "\x1e".join([os.path.abspath(context_file),
                       _expr(seeds, follow, depth, extractors), usd_version])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(k: str) -> str:
    return os.path.join(_cache_dir(), k + ".json")


def layer_signature(stage) -> List[Tuple[str, float, int]]:
    """(realPath, mtime, size) for every on-disk layer the composition used --
    the set whose freshness decides whether a cached pull still holds."""
    sig = []
    for layer in stage.GetUsedLayers():
        rp = layer.realPath
        if not rp:
            continue
        try:
            st = os.stat(rp)
            sig.append((rp, st.st_mtime, st.st_size))
        except OSError:
            sig.append((rp, -1.0, -1))      # missing now -> will never match
    return sorted(sig)


def _fresh(sig) -> bool:
    for rp, mtime, size in sig:
        try:
            st = os.stat(rp)
        except OSError:
            return False
        if st.st_mtime != mtime or st.st_size != size:
            return False
    return bool(sig)        # an empty signature is never a trustworthy hit


def _pull_to_dict(p, sig) -> dict:
    return {
        "context": p.context, "depth": p.depth, "follow": p.follow,
        "members": [{"path": m.path, "via_kind": m.via_kind,
                     "from_member": m.from_member, "note": m.note} for m in p.members],
        "boundary": [{"target": b.target, "kind": b.kind, "reason": b.reason,
                      "omission": b.omission} for b in p.boundary],
        "variant_selections": list(p.variant_selections),
        "layers": [list(x) for x in p.layers],
        "accounting": dict(p.accounting), "fitness": dict(p.fitness),
        "declarations": list(p.declarations),
        "layer_sig": [list(x) for x in sig],
    }


def _pull_from_dict(d):
    from .pull import Pull, PullMember, PullBoundary
    p = Pull(context=d["context"], depth=d["depth"], follow=list(d["follow"]))
    p.members = [PullMember(**m) for m in d["members"]]
    p.boundary = [PullBoundary(**b) for b in d["boundary"]]
    p.variant_selections = list(d["variant_selections"])
    p.layers = [tuple(x) for x in d["layers"]]
    p.accounting = dict(d["accounting"])
    p.fitness = dict(d["fitness"])
    p.declarations = list(d["declarations"])
    return p


def lookup(context_file, seeds, follow, depth, extractors, usd_version):
    """A fresh cached Pull for this exact expression, or None. Never opens the
    stage: reads the entry, re-stats its recorded layers, rebuilds the Pull."""
    try:
        with open(_path(key(context_file, seeds, follow, depth, extractors, usd_version))) as fh:
            d = json.load(fh)
    except (OSError, ValueError):
        return None
    if not _fresh([tuple(x) for x in d.get("layer_sig", [])]):
        return None
    p = _pull_from_dict(d)
    p.accounting["cache"] = "hit"
    return p


def store(context_file, seeds, follow, depth, extractors, usd_version, p, stage) -> None:
    """Record this pull's result keyed by its expression, with the stat
    signature of the layers it used. Best-effort: a write failure never breaks
    the pull (the cache is an optimization, not a source of truth)."""
    try:
        sig = layer_signature(stage)
        k = key(context_file, seeds, follow, depth, extractors, usd_version)
        tmp = _path(k) + ".tmp.%d" % os.getpid()
        with open(tmp, "w") as fh:
            json.dump(_pull_to_dict(p, sig), fh)
        os.replace(tmp, _path(k))            # atomic
    except OSError:
        pass
