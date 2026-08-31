import random

import pytest

from jitsd.ledger import Repo


def _repo(tmp_path):
    r = Repo(tmp_path)
    r.init()
    return r


def _write(tmp_path, name, n, seed):
    p = tmp_path / name
    p.write_bytes(random.Random(seed).randbytes(n))
    return p


def test_save_mints_revisions_and_moves_wip(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 300_000, 1)
    a = r.save("car", f, "tester", "first")
    assert a.rev == "v001"
    assert r.ledger.channels("car")["wip"] == "v001"

    f.write_bytes(random.Random(2).randbytes(300_000))
    b = r.save("car", f, "tester", "second")
    assert b.rev == "v002" and b.parent == "v001"
    assert r.ledger.channels("car")["wip"] == "v002"


def test_identical_save_does_not_mint_a_revision(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 200_000, 3)
    first = r.save("car", f, "tester")
    again = r.save("car", f, "tester")
    assert again.rev == first.rev
    assert r.ledger.revisions("car") == ["v001"]


def test_revision_file_is_readable_usda(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 100_000, 4)
    rev = r.save("car", f, "tester", "hello")
    text = (r.ledger._revdir("car") / "v001.usda").read_text()
    assert text.startswith("#usda 1.0")
    assert "jitsd__revision" in text and rev.blob[:16] in text
    assert r.ledger.read_revision("car", "v001").message == "hello"


def test_promote_and_resolve_ref(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 100_000, 5)
    r.save("car", f, "tester")
    r.promote("car", "v001", "approved")
    assert r.ledger.resolve_ref("car", "@approved") == "v001"
    with pytest.raises(KeyError):
        r.ledger.resolve_ref("car", "v999")


def test_baseline_pins_and_detects_drift(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 200_000, 6)
    r.save("car", f, "tester")
    r.promote("car", "v001", "approved")
    b = r.cut_baseline(label="review")

    assert b.pins == {"car": "v001"}
    assert r.merkle_root(r.resolve()) == b.merkle_root

    f.write_bytes(random.Random(7).randbytes(200_000))
    r.save("car", f, "tester")
    r.promote("car", "v002", "approved")
    assert r.merkle_root(r.resolve()) != b.merkle_root

    # The old baseline still replays exactly.
    assert r.resolve(baseline=b.number) == {"car": "v001"}


def test_back_is_a_pointer_move_only(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 400_000, 8)
    r.save("car", f, "tester")
    f.write_bytes(random.Random(9).randbytes(400_000))
    r.save("car", f, "tester")

    before = r.store.stats().physical_bytes
    r.ledger.set_channel("car", "wip", "v001")
    assert r.ledger.channels("car")["wip"] == "v001"
    assert r.store.stats().physical_bytes == before


def test_gc_preserves_everything_a_baseline_pins(tmp_path):
    r = _repo(tmp_path)
    f = _write(tmp_path, "car.bin", 500_000, 10)
    r.save("car", f, "tester")
    r.promote("car", "v001", "approved")
    r.cut_baseline(label="keep-me")
    for seed in (11, 12, 13):
        f.write_bytes(random.Random(seed).randbytes(500_000))
        r.save("car", f, "tester")

    r.store.gc(r.reachable_blobs())
    pinned = r.ledger.read_revision("car", "v001")
    assert r.store.has_blob(pinned.blob)
    head = r.ledger.read_revision("car", r.ledger.channels("car")["wip"])
    assert r.store.has_blob(head.blob)


# -- contracts ------------------------------------------------------------

EXAMPLES = __import__("pathlib").Path(__file__).resolve().parents[1] / "examples"


def test_promotion_is_gated_on_measured_compatibility(tmp_path):
    """The claim in docs/03-versioning.md, as a test."""
    from jitsd.ledger import BreakingChange

    r = _repo(tmp_path)
    payload = _write(tmp_path, "c.bin", 50_000, 20)
    r.save("chassis", payload, "tester", interface=EXAMPLES / "chassis.iface.usda")
    r.promote("chassis", "v001", "approved")

    # Move a hub far outside its declared envelope.
    text = (EXAMPLES / "chassis.iface.usda").read_text().replace(
        "(1.42, 0.31, 0.78)", "(1.44, 0.31, 0.78)")
    broken = tmp_path / "broken.usda"
    broken.write_text(text)
    r.save("chassis", payload, "tester", interface=broken)

    with pytest.raises(BreakingChange) as e:
        r.promote("chassis", "v002", "approved")
    assert e.value.violations[0].kind == "envelope"

    # The channel did not move.
    assert r.ledger.channels("chassis")["approved"] == "v001"
    # ...unless forced.
    r.promote("chassis", "v002", "approved", force=True)
    assert r.ledger.channels("chassis")["approved"] == "v002"


def test_interface_carries_forward_when_only_the_payload_changes(tmp_path):
    r = _repo(tmp_path)
    payload = _write(tmp_path, "c.bin", 50_000, 21)
    r.save("chassis", payload, "tester", interface=EXAMPLES / "chassis.iface.usda")
    payload.write_bytes(random.Random(22).randbytes(50_000))
    v2 = r.save("chassis", payload, "tester")
    assert v2.rev == "v002"
    assert v2.surface == r.ledger.read_revision("chassis", "v001").surface


def test_bind_across_assets_at_a_channel(tmp_path):
    r = _repo(tmp_path)
    for name in ("chassis", "wheelset"):
        p = _write(tmp_path, name + ".bin", 20_000, hash(name) % 97)
        r.save(name, p, "tester", interface=EXAMPLES / ("%s.iface.usda" % name))
        r.promote(name, "v001", "approved")
    res = r.bind()
    assert res.ok
    (b,) = res.bindings
    assert b.consumer == "wheelset" and len(b.providers) == 4
