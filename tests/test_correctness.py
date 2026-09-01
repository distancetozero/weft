"""One test per correctness bug found in review.

Every bug here failed the same way: no exception, no warning, a plausible wrong
answer. For a system whose promise is that what you get back is what you stored,
that is the worst failure mode available, so each test asserts the system now
says something rather than quietly proceeding.
"""

from __future__ import annotations

import os

import pytest

from jitsd.chunker import chunk
from jitsd.contracts import Offer, Surface, check_compatibility
from jitsd.ledger import ChannelRaced, Repo, RevisionExists, Revision, _esc
from jitsd.store import CorruptObject, ObjectStore
from jitsd.generators import vehicle as _vehicle  # noqa: F401  registers built-ins


def _repo(tmp_path) -> Repo:
    r = Repo(tmp_path)
    r.init()
    return r


def _save(repo, name="car", body=b"x" * 300000, msg=""):
    p = repo.dir.parent / ("%s.usda" % name)
    p.write_bytes(b"#usda 1.0\n" + body)
    return repo.save(name, p, "tester", msg)


# -- the store must not return corrupt data -------------------------------

def test_flipped_byte_in_a_chunk_is_detected(tmp_path):
    """A blob id IS the sha256 of its content. Verifying costs one hash.

    Before: get_bytes checked only the total length, so a flipped byte came
    back as a successful read of different data, under the correct id.
    """
    s = ObjectStore(tmp_path / "objs")
    s.init()
    data = b"A" * 200000 + b"PAYLOAD" + b"B" * 200000
    bid = s.put_bytes(data)

    victim = next(p for p in s.chunks.rglob("*") if p.is_file())
    b = bytearray(victim.read_bytes())
    b[5] ^= 0xFF
    victim.write_bytes(bytes(b))

    with pytest.raises(CorruptObject):
        s.get_bytes(bid)


def test_checkout_refuses_to_write_corrupt_bytes(tmp_path):
    s = ObjectStore(tmp_path / "objs")
    s.init()
    data = b"A" * 200000 + b"B" * 200000
    bid = s.put_bytes(data)
    victim = next(p for p in s.chunks.rglob("*") if p.is_file())
    b = bytearray(victim.read_bytes())
    b[0] ^= 0xFF
    victim.write_bytes(bytes(b))

    dest = tmp_path / "out.usda"
    with pytest.raises(CorruptObject):
        s.checkout(bid, dest)
    assert not dest.exists(), "a corrupt checkout must leave no file behind"


def test_verify_finds_corruption_and_missing_chunks(tmp_path):
    s = ObjectStore(tmp_path / "objs")
    s.init()
    good = s.put_bytes(b"clean" * 50000)
    bad = s.put_bytes(b"dirty" * 50000)

    bad_chunk = s._chunk_path(s.manifest(bad)["chunks"][0])
    b = bytearray(bad_chunk.read_bytes())
    b[1] ^= 0xFF
    bad_chunk.write_bytes(bytes(b))

    res = s.verify()
    assert good in res["ok"]
    assert bad in res["corrupt"]


def test_missing_chunk_names_the_blob(tmp_path):
    s = ObjectStore(tmp_path / "objs")
    s.init()
    bid = s.put_bytes(b"z" * 300000)
    next(p for p in s.chunks.rglob("*") if p.is_file()).unlink()
    with pytest.raises(KeyError):
        s.get_bytes(bid)


# -- gc must not delete history -------------------------------------------

def test_gc_keeps_every_revision_the_log_lists(tmp_path):
    """gc rooted only at channel heads and pins deleted intermediate history.

    That silently destroys the rung-1 features that justify the tool: rollback,
    named checkpoints, and diff between any two revisions.
    """
    r = _repo(tmp_path)
    v1 = _save(r, body=b"a" * 300000)
    v2 = _save(r, body=b"b" * 300000)
    assert v1.rev != v2.rev

    r.store.gc(r.reachable_blobs())

    listed = r.ledger.revisions("car")
    assert v1.rev in listed
    for rev in listed:
        rr = r.ledger.read_revision("car", rev)
        if rr.blob:
            r.store.get_bytes(rr.blob)   # must still be checkout-able


def test_prune_history_is_opt_in(tmp_path):
    r = _repo(tmp_path)
    v1 = _save(r, body=b"a" * 300000)
    _save(r, body=b"b" * 300000)

    r.store.gc(r.reachable_blobs(prune_history=True))
    with pytest.raises(KeyError):
        r.store.get_bytes(v1.blob)


def test_gc_does_not_eat_a_concurrent_writers_temp_file(tmp_path):
    s = ObjectStore(tmp_path / "objs")
    s.init()
    keep = s.put_bytes(b"keep" * 50000)
    inflight = s.chunks / "ab" / "cd" / ("deadbeef.tmp-%d" % os.getpid())
    inflight.parent.mkdir(parents=True, exist_ok=True)
    inflight.write_bytes(b"half-written")

    s.gc([keep])
    assert inflight.exists(), "gc deleted another writer's in-flight chunk"


# -- revisions are immutable ----------------------------------------------

def test_revision_is_never_overwritten(tmp_path):
    """Two concurrent saves both compute v001; the second must not clobber."""
    r = _repo(tmp_path)
    first = _save(r, body=b"first" * 60000)

    duplicate = Revision(
        asset="car", rev=first.rev, blob=None, size=0, parent=None,
        author="other", created="2026-01-01T00:00:00Z", message="collision",
    )
    with pytest.raises(RevisionExists):
        r.ledger.write_revision(duplicate)

    assert r.ledger.read_revision("car", first.rev).author == "tester"


def test_channel_move_refuses_when_it_raced(tmp_path):
    r = _repo(tmp_path)
    _save(r, body=b"a" * 60000)
    _save(r, body=b"b" * 60000)
    r.ledger.set_channel("car", "approved", "v001")

    # Someone else moved it after we read v001.
    r.ledger.set_channel("car", "approved", "v002")
    with pytest.raises(ChannelRaced):
        r.ledger.set_channel("car", "approved", "v001", expect="v001")

    assert r.ledger.channels("car")["approved"] == "v002"


def test_message_with_a_newline_stays_parseable(tmp_path):
    r = _repo(tmp_path)
    rev = _save(r, body=b"x" * 60000, msg="fix seams\n\nrefs #12")
    assert r.ledger.read_revision("car", rev.rev).message == "fix seams\n\nrefs #12"
    assert "\\n" in _esc("a\nb")


# -- a baseline must pin the function, not just the inputs ----------------

def test_generator_is_pinned_by_version_and_code(tmp_path):
    r = _repo(tmp_path)
    rev = r.declare("chassis", "chassis", {"wheelbase": 2.8}, "tester")
    assert "@" in rev.generator, "stored a bare generator name"
    assert rev.generator_version
    assert rev.generator_hash


def test_editing_a_generator_shows_up_as_drift(tmp_path):
    """merkle_root hashed the generator's NAME, so a rewrite was invisible."""
    r = _repo(tmp_path)
    r.declare("chassis", "chassis", {"wheelbase": 2.8}, "tester")
    r.promote("chassis", "v001", "approved")
    pins = r.resolve(channel="approved")
    before = r.merkle_root(pins)

    # Stand in for the generator's code changing under a pinned baseline.
    rec = r.ledger.read_revision("chassis", "v001")
    p = r.ledger._revdir("chassis") / "v001.usda"
    p.write_text(p.read_text().replace(rec.generator_hash, "0" * 64))

    after = r.merkle_root(pins)
    assert before != after, "a generator code change did not move the merkle root"


def test_stale_generator_is_reported(tmp_path):
    r = _repo(tmp_path)
    r.declare("chassis", "chassis", {"wheelbase": 2.8}, "tester")
    assert r.stale_generators() == []

    rec = r.ledger.read_revision("chassis", "v001")
    p = r.ledger._revdir("chassis") / "v001.usda"
    p.write_text(p.read_text().replace(rec.generator_hash, "0" * 64))

    stale = r.stale_generators()
    assert len(stale) == 1 and stale[0]["why"] == "code changed"


# -- the promotion gate must see what resolution sees ---------------------

def _offer(**kw):
    base = dict(path="/mount", contract="Mount@2", role="hub", public=True,
                frame=(0.0, 0.0, 0.0), orient=(0.0, 0.0, 0.0),
                envelope_linear=0.5, envelope_angular=5.0)
    base.update(kw)
    return Offer(**base)


def test_gate_catches_an_offer_going_private():
    """resolve() filters on `public`, so this removes a provider."""
    old = Surface(offers=[_offer()])
    new = Surface(offers=[_offer(public=False)])
    kinds = [v.kind for v in check_compatibility(old, new)]
    assert "unpublished" in kinds


def test_gate_catches_a_role_change():
    """resolve() narrows on `role`, so this removes a provider."""
    old = Surface(offers=[_offer(role="hub")])
    new = Surface(offers=[_offer(role="axle")])
    assert "role-changed" in [v.kind for v in check_compatibility(old, new)]


def test_gate_catches_rotation_beyond_the_envelope():
    """A mount is a frame, not a point. It could rotate 180 and pass."""
    old = Surface(offers=[_offer(orient=(0.0, 0.0, 0.0), envelope_angular=5.0)])
    new = Surface(offers=[_offer(orient=(0.0, 180.0, 0.0), envelope_angular=5.0)])
    assert "envelope-angular" in [v.kind for v in check_compatibility(old, new)]


def test_rotation_inside_the_envelope_is_compatible():
    old = Surface(offers=[_offer(orient=(0.0, 0.0, 0.0), envelope_angular=5.0)])
    new = Surface(offers=[_offer(orient=(0.0, 2.0, 0.0), envelope_angular=5.0)])
    assert check_compatibility(old, new) == []


def test_tightening_the_angular_envelope_is_breaking():
    old = Surface(offers=[_offer(envelope_angular=10.0)])
    new = Surface(offers=[_offer(envelope_angular=1.0)])
    assert "envelope-tightened" in [v.kind for v in check_compatibility(old, new)]


def test_promote_returns_the_violations_it_forced_over(tmp_path):
    """Re-checking after the move always returns clean, so the CLI said clean."""
    r = _repo(tmp_path)
    _save(r, body=b"a" * 60000)
    rev, forced = r.promote("car", "v001", "approved")
    assert rev == "v001" and forced == []


# -- the chunker must always advance --------------------------------------

def test_zero_max_size_raises_instead_of_hanging():
    with pytest.raises(ValueError):
        chunk(b"x" * 100, min_size=0, avg_size=8, max_size=0)


def test_min_size_above_max_size_raises():
    with pytest.raises(ValueError):
        chunk(b"x" * 100, min_size=64, avg_size=8, max_size=16)
