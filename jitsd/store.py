"""Content-addressed object store.

Two levels, because they answer different questions:

  chunks/   deduplicated variable-size pieces. Physical bytes on disk.
  blobs/    a manifest per stored file: its size and its chunk list.

A blob's id is the sha256 of the whole file, so identical files collapse at the
blob level and near-identical files collapse at the chunk level. Nothing here is
ever mutated or overwritten -- writes are atomic renames, and a chunk that
already exists is simply not written again.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from . import chunker
from .chunker import chunk

READ_BUF = 8 * 1024 * 1024

# In-flight writes are named <target>.tmp-<pid>. gc() and stats() must both
# recognise the pattern: gc deleting another process's temp file destroys a
# chunk that writer is about to reference, and stats counting one inflates the
# reported dedup ratio.
TMP_MARK = ".tmp-"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            b = fh.read(READ_BUF)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _fsync_dir(path: Path) -> None:
    """Durably record a rename. Best-effort: not every platform allows it."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


class CorruptObject(IOError):
    """Stored bytes do not hash to the id they are filed under."""


@dataclass
class Stats:
    blobs: int
    logical_bytes: int
    chunks: int
    physical_bytes: int

    @property
    def ratio(self) -> float:
        return self.logical_bytes / self.physical_bytes if self.physical_bytes else 1.0


class ObjectStore:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.chunks = self.root / "chunks"
        self.blobs = self.root / "blobs"
        self.config_path = self.root / "config.json"
        self._params: Optional[Dict[str, int]] = None

    def init(self) -> None:
        self.chunks.mkdir(parents=True, exist_ok=True)
        self.blobs.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self.config_path.write_text(json.dumps(self.default_params(), indent=2) + "\n")

    # -- chunker parameters ----------------------------------------------
    @staticmethod
    def default_params() -> Dict[str, int]:
        return {"min_size": chunker.MIN_SIZE,
                "avg_size": chunker.AVG_SIZE,
                "max_size": chunker.MAX_SIZE}

    def params(self) -> Dict[str, int]:
        """Chunker settings this store was created with.

        Recorded because they are not a tuning knob after the fact: different
        boundaries mean nothing new dedups against anything already stored, and
        the damage is silent -- the store keeps working, it just stops saving
        space. A store is therefore self-describing, and re-chunking is an
        explicit migration rather than an accident.
        """
        if self._params is None:
            if self.config_path.exists():
                loaded = json.loads(self.config_path.read_text())
                want = ("min_size", "avg_size", "max_size")
                missing = [k for k in want if k not in loaded]
                if missing:
                    raise ValueError(
                        "%s is missing %s" % (self.config_path, ", ".join(missing)))
                # A store's own config is the one place these arrive unchecked.
                chunker.validate_params(loaded["min_size"], loaded["avg_size"],
                                        loaded["max_size"])
                self._params = {k: loaded[k] for k in want}
            else:
                self._params = self.default_params()
        return self._params

    # -- paths ------------------------------------------------------------
    def _chunk_path(self, digest: str) -> Path:
        return self.chunks / digest[:2] / digest[2:4] / digest

    def _blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / (digest + ".json")

    # -- writes -----------------------------------------------------------
    def _write_atomic(self, path: Path, data: bytes) -> bool:
        """Returns True if the object was newly written, False if it existed.

        fsync before the rename and on the parent directory after it. Without
        the first, power loss can leave the file at its final name with zero
        bytes -- and since the name is the content hash, that is a blob the
        ledger believes in and the store cannot produce.
        """
        if path.exists():
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + TMP_MARK + str(os.getpid()))
        try:
            with tmp.open("wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
            _fsync_dir(path.parent)
        except OSError:
            tmp.unlink(missing_ok=True)
            raise
        return True

    def put_bytes(self, data: bytes) -> str:
        """Store one payload. Returns its blob id."""
        blob_id = sha256_bytes(data)
        bp = self._blob_path(blob_id)
        if bp.exists():
            return blob_id

        chunk_ids: List[str] = []
        for piece in chunk(data, **self.params()):
            cid = sha256_bytes(piece)
            chunk_ids.append(cid)
            self._write_atomic(self._chunk_path(cid), piece)

        manifest = json.dumps(
            {"size": len(data), "chunks": chunk_ids}, separators=(",", ":")
        ).encode()
        self._write_atomic(bp, manifest)
        return blob_id

    def put_file(self, path: Path) -> str:
        return self.put_bytes(Path(path).read_bytes())

    # -- reads ------------------------------------------------------------
    def has_blob(self, blob_id: str) -> bool:
        return self._blob_path(blob_id).exists()

    def manifest(self, blob_id: str) -> Dict:
        bp = self._blob_path(blob_id)
        if not bp.exists():
            raise KeyError("no such blob: %s" % blob_id)
        return json.loads(bp.read_text())

    def _read_chunk(self, cid: str) -> bytes:
        p = self._chunk_path(cid)
        if not p.exists():
            raise KeyError("blob references missing chunk %s" % cid)
        return p.read_bytes()

    def get_bytes(self, blob_id: str, verify: bool = True) -> bytes:
        """Reassemble a blob, and check it is the blob that was asked for.

        A blob id IS the sha256 of its content, so verification costs one hash
        and turns silent corruption into an error. Without it a flipped byte in
        a chunk file comes back as a successful read of the wrong data -- the
        worst failure available to a store whose entire promise is that what
        you get back is what you put in.
        """
        man = self.manifest(blob_id)
        out = bytearray()
        for cid in man["chunks"]:
            out += self._read_chunk(cid)
        if len(out) != man["size"]:
            raise CorruptObject(
                "blob %s: expected %d bytes, reassembled %d"
                % (blob_id, man["size"], len(out)))
        data = bytes(out)
        if verify:
            actual = sha256_bytes(data)
            if actual != blob_id:
                raise CorruptObject(
                    "blob %s reassembles to %s -- a chunk is corrupt"
                    % (blob_id, actual))
        return data

    def checkout(self, blob_id: str, dest: Path, verify: bool = True) -> None:
        """Materialise a blob to a file, hashing as it goes.

        Written to a temp file and renamed, so a verification failure cannot
        leave a corrupt file at the destination path.
        """
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        man = self.manifest(blob_id)
        tmp = dest.with_suffix(dest.suffix + TMP_MARK + str(os.getpid()))
        h = hashlib.sha256()
        written = 0
        try:
            with tmp.open("wb") as fh:
                for cid in man["chunks"]:
                    piece = self._read_chunk(cid)
                    h.update(piece)
                    written += len(piece)
                    fh.write(piece)
                fh.flush()
                os.fsync(fh.fileno())
            if written != man["size"]:
                raise CorruptObject(
                    "blob %s: expected %d bytes, wrote %d"
                    % (blob_id, man["size"], written))
            if verify and h.hexdigest() != blob_id:
                raise CorruptObject(
                    "blob %s reassembles to %s -- a chunk is corrupt"
                    % (blob_id, h.hexdigest()))
            os.replace(tmp, dest)
            _fsync_dir(dest.parent)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

    def verify(self) -> Dict[str, List[str]]:
        """Check every blob against its own id. The missing fsck.

        Returns {"ok": [...], "corrupt": [...], "missing_chunks": [...]}.
        """
        out: Dict[str, List[str]] = {"ok": [], "corrupt": [], "missing_chunks": []}
        for bid in sorted(self.iter_blob_ids()):
            try:
                self.get_bytes(bid, verify=True)
            except KeyError:
                out["missing_chunks"].append(bid)
            except CorruptObject:
                out["corrupt"].append(bid)
            else:
                out["ok"].append(bid)
        return out

    # -- introspection ----------------------------------------------------
    def iter_blob_ids(self) -> Iterable[str]:
        for p in self.blobs.rglob("*.json"):
            yield p.stem

    def stats(self) -> Stats:
        logical = 0
        nblobs = 0
        for bid in self.iter_blob_ids():
            logical += self.manifest(bid)["size"]
            nblobs += 1
        physical = 0
        nchunks = 0
        for p in self.chunks.rglob("*"):
            if p.is_file() and TMP_MARK not in p.name:
                physical += p.stat().st_size
                nchunks += 1
        return Stats(nblobs, logical, nchunks, physical)

    # -- gc ---------------------------------------------------------------
    def gc(self, reachable_blob_ids: Iterable[str]) -> Dict[str, int]:
        """Drop blobs and chunks not reachable from the given roots.

        Chunks are swept before blobs are unlinked, so an interrupted gc leaves
        a blob whose chunks are gone rather than chunks no blob claims -- the
        first is detectable by `verify`, the second is invisible.

        In-flight temp files are never touched: they belong to a concurrent
        writer and are not in any keep set by construction.
        """
        keep_blobs = set(reachable_blob_ids)
        doomed = [bid for bid in self.iter_blob_ids() if bid not in keep_blobs]

        keep_chunks = set()
        for bid in keep_blobs:
            try:
                keep_chunks.update(self.manifest(bid)["chunks"])
            except KeyError:
                continue  # a root we do not actually hold; nothing to keep

        dropped_chunks = 0
        freed = 0
        for p in list(self.chunks.rglob("*")):
            if not p.is_file() or TMP_MARK in p.name:
                continue
            if p.name in keep_chunks:
                continue
            freed += p.stat().st_size
            p.unlink()
            dropped_chunks += 1

        dropped_blobs = 0
        for bid in doomed:
            self._blob_path(bid).unlink(missing_ok=True)
            dropped_blobs += 1

        return {"blobs": dropped_blobs, "chunks": dropped_chunks, "bytes": freed}
