"""Measure the storage claim in docs/06-storage.md.

The claim: "200 saves of a 4 GB asset cost ~4 GB plus deltas, not 800 GB."

Three edit patterns, because they do not behave the same and the docs should
not pretend they do:

  local     an artist reworks one region      (localised byte range)
  scattered several regions touched at once   (a few edits per save)
  global    a re-export shifts every value    (worst case for any chunker)
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jitsd.store import ObjectStore  # noqa: E402


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(n) < 1024 or unit == "GiB":
            return "%.1f %s" % (n, unit)
        n /= 1024.0
    return "%.1f GiB" % n


def edit_local(buf: bytearray, rng: random.Random, frac: float) -> int:
    span = max(1, int(len(buf) * frac))
    off = rng.randrange(0, max(1, len(buf) - span))
    buf[off:off + span] = rng.randbytes(span)
    return span


def edit_scattered(buf: bytearray, rng: random.Random, frac: float) -> int:
    total = 0
    per = max(1, int(len(buf) * frac / 5))
    for _ in range(5):
        off = rng.randrange(0, max(1, len(buf) - per))
        buf[off:off + per] = rng.randbytes(per)
        total += per
    return total


def edit_global(buf: bytearray, rng: random.Random, frac: float) -> int:
    # Perturb one byte in every 512 -- the shape of a re-export where every
    # float moves in the last bits.
    for i in range(0, len(buf), 512):
        buf[i] = rng.randrange(256)
    return len(buf) // 512


PATTERNS = {"local": edit_local, "scattered": edit_scattered, "global": edit_global}


def run(pattern: str, size_mb: int, saves: int, frac: float) -> dict:
    rng = random.Random(0xC0FFEE)
    tmp = Path(tempfile.mkdtemp(prefix="jitsd-bench-"))
    try:
        store = ObjectStore(tmp / "objects")
        store.init()
        buf = bytearray(rng.randbytes(size_mb * 1024 * 1024))
        edit = PATTERNS[pattern]

        store.put_bytes(bytes(buf))
        after_first = store.stats().physical_bytes
        edited_bytes = 0

        for _ in range(saves - 1):
            edited_bytes += edit(buf, rng, frac)
            store.put_bytes(bytes(buf))

        st = store.stats()
        return {
            "pattern": pattern,
            "saves": saves,
            "asset": size_mb * 1024 * 1024,
            "first": after_first,
            "logical": st.logical_bytes,
            "physical": st.physical_bytes,
            "chunks": st.chunks,
            "edited": edited_bytes,
        }
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--size-mb", type=int, default=128)
    ap.add_argument("--saves", type=int, default=40)
    ap.add_argument("--edit-fraction", type=float, default=0.005,
                    help="portion of the asset changed per save (default 0.5%%)")
    ap.add_argument("--patterns", default="local,scattered,global")
    args = ap.parse_args()

    print("asset %s  ·  %d saves  ·  %.2f%% edited per save\n"
          % (human(args.size_mb * 1024 * 1024), args.saves, args.edit_fraction * 100))
    print("%-10s %12s %12s %10s %12s"
          % ("pattern", "as files", "on disk", "dedup", "vs 1 copy"))
    print("-" * 62)

    rows = []
    for pattern in args.patterns.split(","):
        r = run(pattern.strip(), args.size_mb, args.saves, args.edit_fraction)
        rows.append(r)
        ratio = r["logical"] / r["physical"] if r["physical"] else 1.0
        overhead = r["physical"] / r["asset"]
        print("%-10s %12s %12s %9.1fx %11.2fx"
              % (r["pattern"], human(r["logical"]), human(r["physical"]), ratio, overhead))

    print()
    for r in rows:
        per_save = (r["physical"] - r["first"]) / max(1, r["saves"] - 1)
        print("%-10s  %s stored per additional save (edited ~%s)"
              % (r["pattern"], human(per_save), human(r["edited"] / max(1, r["saves"] - 1))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
