"""Content-defined chunking.

Whole-file content addressing gives ZERO dedup for a large asset with a small
edit: one changed byte changes the file hash, so the whole file is stored
again. The storage claim in docs/06-storage.md only holds with content-defined
chunk boundaries, so that is what this implements.

Gear hash, rolling over a 64-byte window:

    h[i] = (h[i-1] << 1) + G[data[i]]        (mod 2**64)

Expanding the recurrence, terms older than 64 bytes have been shifted out:

    h[i] = sum(G[data[i-j]] << j for j in 0..63)

which is a sum of 64 shifted copies of a lookup table applied to the data --
so it vectorises, even though the recurrence looks strictly sequential. The
numpy path uses that; the pure-Python path walks the recurrence directly. Both
must produce identical boundaries (tests/test_chunker.py asserts it).
"""

from __future__ import annotations

import random
from typing import Iterator, List, Optional, Tuple

# Deterministic gear table. Fixed seed: boundaries must be reproducible across
# machines and versions, or the whole store stops deduplicating.
_rng = random.Random(0x1BADB002)
GEAR: Tuple[int, ...] = tuple(_rng.getrandbits(64) for _ in range(256))

MASK64 = (1 << 64) - 1
WINDOW = 64

# ~1 MiB average. Chosen for 3D payloads: a localised edit costs ~2-3 chunks,
# and a 4 GB asset yields ~4000 chunks rather than millions of tiny files.
MIN_SIZE = 256 * 1024
AVG_SIZE = 1024 * 1024
MAX_SIZE = 4 * 1024 * 1024


def _mask_for(avg_size: int) -> int:
    bits = max(1, avg_size.bit_length() - 1)
    return (1 << bits) - 1


def cut_points_pure(data: bytes, min_size: int, avg_size: int, max_size: int) -> List[int]:
    """Reference implementation: walk the recurrence one byte at a time."""
    mask = _mask_for(avg_size)
    cuts: List[int] = []
    n = len(data)
    start = 0
    while start < n:
        if n - start <= min_size:
            cuts.append(n)
            break
        h = 0
        limit = min(start + max_size, n)
        i = start
        # The window must fill before a boundary is meaningful, and we never
        # cut below min_size anyway, so roll silently up to the minimum.
        while i < min(start + min_size, limit):
            h = ((h << 1) + GEAR[data[i]]) & MASK64
            i += 1
        cut = limit
        while i < limit:
            h = ((h << 1) + GEAR[data[i]]) & MASK64
            i += 1
            if (h & mask) == 0:
                cut = i
                break
        cuts.append(cut)
        start = cut
    return cuts


def cut_points_numpy(data: bytes, min_size: int, avg_size: int, max_size: int) -> List[int]:
    """Vectorised, via a cascade filter over a min-size-skipping window.

    The naive vectorisation computes all 64 shifted terms across the whole
    file. It is memory-bound and measures ~2 MB/s -- useless. Three
    observations collapse it:

    1. Only the low `bits` bits of h are ever tested, so terms shifted further
       than `bits` cannot affect the answer: 64 passes become `bits` passes.
    2. Adding term j only touches bits >= j, so once the low j bits of the
       partial sum are non-zero they can never return to zero. The requirement
       is monotone, so a position failing at level j is discarded and the
       candidate set roughly halves per level. Total gather work is
       n/2 + n/4 + ... ~= n rather than n * bits.
    3. No boundary may fall within min_size of the previous one, so those bytes
       are never evaluated, and the search can stop at the first hit rather
       than finding every candidate in the file.

    Level 0 is a parity test against a uint8 table, which keeps the one
    full-width pass over the data at 1 byte per position instead of 4.
    """
    import numpy as np

    mask = _mask_for(avg_size)
    bits = mask.bit_length()
    n = len(data)
    if n == 0:
        return []

    dtype = np.uint32 if bits <= 24 else np.uint64
    gear_low = np.array([g & mask for g in GEAR], dtype=dtype)
    odd = np.array([g & 1 for g in GEAR], dtype=np.uint8)

    arr = np.frombuffer(data, dtype=np.uint8)
    SCAN = 1 << 20

    def first_cut(lo: int, hi: int) -> Optional[int]:
        """First boundary in [lo, hi), scanning forward in windows."""
        pos = lo
        while pos < hi:
            end = min(pos + SCAN, hi)
            seg = arr[pos:end]
            keep = odd[seg] == 0
            idx = np.flatnonzero(keep).astype(np.int64) + pos
            if idx.size:
                S = gear_low[arr[idx]].astype(dtype, copy=True)
                for j in range(1, bits):
                    if idx.size == 0:
                        break
                    ok = idx >= j
                    idx, S = idx[ok], S[ok]
                    if idx.size == 0:
                        break
                    term = (gear_low[arr[idx - j]] & dtype((1 << (bits - j)) - 1)) << dtype(j)
                    S = (S + term) & dtype(mask)
                    ok = (S & dtype((1 << (j + 1)) - 1)) == 0
                    idx, S = idx[ok], S[ok]
                if idx.size:
                    return int(idx[0]) + 1
            pos = end
        return None

    out: List[int] = []
    pos = 0
    while pos < n:
        if n - pos <= min_size:
            out.append(n)
            break
        hi = min(pos + max_size, n)
        hit = first_cut(pos + min_size, hi)
        cut = hit if hit is not None else hi
        out.append(cut)
        pos = cut
    return out


def _have_numpy() -> bool:
    try:
        import numpy  # noqa: F401
        return True
    except ImportError:
        return False


def chunk(
    data: bytes,
    min_size: int = MIN_SIZE,
    avg_size: int = AVG_SIZE,
    max_size: int = MAX_SIZE,
    force_pure: bool = False,
) -> Iterator[bytes]:
    """Split data at content-defined boundaries."""
    if not data:
        return
    fn = cut_points_pure if (force_pure or not _have_numpy()) else cut_points_numpy
    prev = 0
    for cut in fn(data, min_size, avg_size, max_size):
        yield data[prev:cut]
        prev = cut
