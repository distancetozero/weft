import random

import pytest

from jitsd.chunker import chunk, cut_points_numpy, cut_points_pure

MIN, AVG, MAX = 1024, 4096, 16384


def _data(n, seed=7):
    return random.Random(seed).randbytes(n)


def test_numpy_and_pure_agree():
    """The vectorised path must produce byte-identical boundaries.

    Skips without numpy: there is no second backend to compare against, and
    rung 1 must run with no optional dependency installed at all.

    If it does not, two machines chunk the same file differently and the store
    silently stops deduplicating.
    """
    pytest.importorskip("numpy")
    for n in (0, 1, 100, 1024, 5000, 100_000, 300_000):
        d = _data(n)
        assert cut_points_pure(d, MIN, AVG, MAX) == cut_points_numpy(d, MIN, AVG, MAX), n


def test_chunks_reassemble():
    d = _data(250_000)
    assert b"".join(chunk(d, MIN, AVG, MAX)) == d


def test_chunk_size_bounds():
    d = _data(500_000)
    pieces = list(chunk(d, MIN, AVG, MAX))
    for p in pieces[:-1]:
        assert MIN <= len(p) <= MAX
    assert len(pieces[-1]) <= MAX


def test_boundaries_are_content_defined():
    """An insertion early in the file must not reshuffle every later boundary.

    This is the whole point: with fixed-size blocks, inserting one byte shifts
    all subsequent blocks and dedup collapses to zero.
    """
    d = _data(400_000)
    inserted = d[:1000] + b"\x00" * 64 + d[1000:]
    a = set(chunk(d, MIN, AVG, MAX))
    b = set(chunk(inserted, MIN, AVG, MAX))
    assert len(a & b) / len(a) > 0.8
