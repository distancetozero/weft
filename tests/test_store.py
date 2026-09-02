import random

from weft.store import ObjectStore


def _store(tmp_path):
    s = ObjectStore(tmp_path / "objects")
    s.init()
    return s


def test_roundtrip(tmp_path):
    s = _store(tmp_path)
    data = random.Random(1).randbytes(3_000_000)
    bid = s.put_bytes(data)
    assert s.get_bytes(bid) == data


def test_identical_content_stores_once(tmp_path):
    s = _store(tmp_path)
    data = random.Random(2).randbytes(2_000_000)
    a = s.put_bytes(data)
    before = s.stats().physical_bytes
    b = s.put_bytes(data)
    assert a == b
    assert s.stats().physical_bytes == before


def test_localised_edit_costs_little(tmp_path):
    """The claim in docs/06-storage.md, as a test."""
    s = _store(tmp_path)
    base = bytearray(random.Random(3).randbytes(16 * 1024 * 1024))
    s.put_bytes(bytes(base))
    first = s.stats().physical_bytes
    base[8_000_000:8_000_128] = b"E" * 128
    s.put_bytes(bytes(base))
    added = s.stats().physical_bytes - first
    # A 128-byte edit must cost far less than a second copy of the asset.
    assert added < len(base) * 0.4


def test_checkout_is_byte_identical(tmp_path):
    s = _store(tmp_path)
    data = random.Random(4).randbytes(5_000_000)
    bid = s.put_bytes(data)
    dest = tmp_path / "out.bin"
    s.checkout(bid, dest)
    assert dest.read_bytes() == data


def test_gc_keeps_reachable_and_drops_the_rest(tmp_path):
    s = _store(tmp_path)
    keep = s.put_bytes(random.Random(5).randbytes(2_000_000))
    drop = s.put_bytes(random.Random(6).randbytes(2_000_000))
    res = s.gc([keep])
    assert res["blobs"] == 1
    assert s.has_blob(keep) and not s.has_blob(drop)
    assert len(s.get_bytes(keep)) == 2_000_000


def test_store_records_its_chunker_parameters(tmp_path):
    """Chunk parameters are not a tuning knob after the fact: changing them
    means nothing new dedups against anything already stored, silently."""
    import json

    from weft import chunker

    s = _store(tmp_path)
    cfg = json.loads((tmp_path / "objects" / "config.json").read_text())
    assert cfg == {"min_size": chunker.MIN_SIZE,
                   "avg_size": chunker.AVG_SIZE,
                   "max_size": chunker.MAX_SIZE}


def test_store_uses_its_recorded_parameters_not_the_current_default(tmp_path):
    import json

    s = _store(tmp_path)
    (tmp_path / "objects" / "config.json").write_text(
        json.dumps({"min_size": 2048, "avg_size": 8192, "max_size": 32768}))
    s._params = None
    data = random.Random(9).randbytes(400_000)
    bid = s.put_bytes(data)
    assert s.get_bytes(bid) == data
    # Far more chunks than the 64 KiB default would produce.
    assert len(s.manifest(bid)["chunks"]) > 20
